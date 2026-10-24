"""Background data synchronisation with progress status for the UI."""
import threading, datetime, time, traceback, json
from . import db
from .config import HISTORY_DAYS, INSTI_DAYS
from .fetch import twse, tpex, fundamentals, tdcc, news as newsfetch, intl, margin
from .fetch.common import weekdays_back, iso
from .analysis import newsrules

status = {"running": False, "task": "", "step": "", "progress": 0, "total": 0, "log": [], "error": None, "started": None}
_lock = threading.Lock()

def _log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    status["log"].append(f"[{ts}] {msg}")
    status["log"] = status["log"][-80:]
    print(msg, flush=True)

def _set(step, progress=0, total=0):
    status.update(step=step, progress=progress, total=total)

def sync_prices(days=HISTORY_DAYS):
    """Fetch daily quotes (TWSE + TPEx) for each weekday not yet stored."""
    dates = weekdays_back(days)
    todo = [d for d in dates if db.fetched("daily", iso(d)) not in ("ok", "holiday")]
    # today's data is only final after ~15:00; don't mark a 'holiday' before then
    now = datetime.datetime.now()
    _set("下載每日行情", 0, len(todo))
    for i, d in enumerate(todo):
        got_any, failed = False, False
        for name, fn in (("TWSE", twse.fetch_daily), ("TPEx", tpex.fetch_daily)):
            try:
                res = fn(d)
            except Exception as e:
                _log(f"{name} {iso(d)} 失敗: {e}"); res = None; failed = True
            if res:
                rows, names = res
                db.executemany("INSERT OR REPLACE INTO daily(code,date,open,high,low,close,volume,amount,txn) VALUES(?,?,?,?,?,?,?,?,?)", rows)
                db.executemany("INSERT OR IGNORE INTO stocks(code,name,market,industry) VALUES(?,?,?,'')", [(c, n, m) for c, n, m in names])
                got_any = True
        if got_any:
            db.mark_fetched("daily", iso(d), "ok")
        elif d < now.date() and not failed:
            db.mark_fetched("daily", iso(d), "holiday")  # 交易所明確回「無資料」才算假日；當天或抓取失敗都不標記，下次同步再試
        _set("下載每日行情", i + 1, len(todo))
    _log(f"行情同步完成 ({len(todo)} 日)")

def sync_insti(days=INSTI_DAYS):
    dates = weekdays_back(days)
    todo = [d for d in dates if db.fetched("insti", iso(d)) not in ("ok", "holiday")]
    now = datetime.datetime.now()
    _set("下載三大法人", 0, len(todo))
    for i, d in enumerate(todo):
        got_any, failed = False, False
        for name, fn in (("TWSE", twse.fetch_insti), ("TPEx", tpex.fetch_insti)):
            try: res = fn(d)
            except Exception as e:
                _log(f"{name} 法人 {iso(d)} 失敗: {e}"); res = None; failed = True
            if res:
                db.executemany("INSERT OR REPLACE INTO insti(code,date,foreign_net,trust_net,dealer_net,total_net) VALUES(?,?,?,?,?,?)", res)
                got_any = True
        if got_any:
            db.mark_fetched("insti", iso(d), "ok")
            for name, fn in (("TWSE", margin.fetch_twse), ("TPEx", margin.fetch_tpex)):
                try:
                    mr = fn(d)
                    if mr: db.executemany("INSERT OR REPLACE INTO margin(code,date,fin_balance,fin_change,short_balance,short_change) VALUES(?,?,?,?,?,?)", mr)
                except Exception as e: _log(f"{name} 融資券 {iso(d)}: {e}")
            try:
                tot = twse.fetch_insti_total(d)
                if tot: db.set_meta(f"insti_total:{iso(d)}", tot)
            except Exception as e: _log(f"法人合計 {iso(d)}: {e}")
            try:
                idx = twse.fetch_index_summary(d)
                if idx: db.set_meta(f"index:{iso(d)}", idx)
            except Exception as e: _log(f"指數 {iso(d)}: {e}")
        elif d < now.date() and not failed:
            db.mark_fetched("insti", iso(d), "holiday")  # 法人資料約 16:00 後才公布；當天沒抓到或抓取失敗都不標記
        _set("下載三大法人", i + 1, len(todo))
    _log(f"法人同步完成 ({len(todo)} 日)")

def sync_news():
    _set("擷取新聞", 0, 3)
    items = newsfetch.fetch_all(progress=lambda a, b: _set("擷取新聞", a, b))
    n = newsrules.store(items)
    db.set_meta("news_updated", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    _log(f"新聞更新完成: {len(items)} 則 (新增 {n})")
    return len(items)

def sync_intl():
    _set("擷取國際行情", 0, 1)
    intl.update()
    _set("擷取國際行情", 1, 1)
    _log("國際行情更新完成")

def sync_fundamentals():
    _set("擷取基本面 (營收/EPS/本益比)", 0, 1)
    n = fundamentals.update_all()
    _set("擷取基本面", 1, 1)
    _log(f"基本面更新完成 ({n} 檔)")

def sync_tdcc():
    _set("擷取集保大戶資料", 0, 1)
    d, n = tdcc.update_bulk()
    _set("擷取集保大戶資料", 1, 1)
    _log(f"集保資料 {d} 完成 ({n} 列)")

def _run(tasks, name):
    with _lock:
        status.update(running=True, task=name, error=None, started=datetime.datetime.now().strftime("%H:%M:%S"))
        try:
            for t in tasks:
                try: t()
                except Exception as e:
                    _log(f"{t.__name__} 錯誤: {e}")
                    traceback.print_exc()
            from .analysis import engine
            _set("計算技術面/籌碼面評分", 0, 1)
            engine.rebuild()
            if name in ("all", "tdcc", "prices"):
                try:
                    codes = engine.candidates_for_tdcc(70)
                    _set("查詢集保大戶週變化", 0, len(codes))
                    tdcc.fetch_stocks_weeks(codes, weeks=2, progress=lambda a, b: _set("查詢集保大戶週變化", a, b))
                    engine.rebuild()
                except Exception as e:
                    _log(f"集保大戶查詢錯誤: {e}")
            if name in ("all", "prices"):
                try:
                    from .analysis import backtest
                    _set("計算訊號勝率回測", 0, 1)
                    backtest.run()
                except Exception as e: _log(f"回測錯誤: {e}")
            _set("完成", 1, 1)
            _log("分析完成")
        except Exception as e:
            status["error"] = str(e); traceback.print_exc()
        finally:
            status["running"] = False
            db.set_meta("last_sync", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))

def start(what="all"):
    if status["running"]: return False
    tasks = {
        "all": [sync_intl, sync_news, sync_fundamentals, sync_prices, sync_insti, sync_tdcc],
        "news": [sync_news, sync_intl],
        "prices": [sync_prices, sync_insti],
        "fundamentals": [sync_fundamentals],
        "tdcc": [sync_tdcc],
        "intl": [sync_intl],
    }.get(what, [sync_news])
    threading.Thread(target=_run, args=(tasks, what), daemon=True).start()
    return True
