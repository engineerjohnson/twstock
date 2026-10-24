"""GitHub Actions 用：同步資料 (同步執行、不開伺服器) 後產生靜態網站。
用法:
  python -m app.cloud_sync news      # 新聞 + 國際行情
  python -m app.cloud_sync full      # 行情/法人/融資券/基本面/集保 + 回測 + AI
  python -m app.cloud_sync auto      # 自動判斷: 有交易日的行情/法人尚未抓到 (收盤後) 就跑 full，否則 news
GitHub 的排程常延遲或整點被略過，所以 auto 不看「現在幾點」而是看「資料缺不缺」：
只要最近 7 天內任何一個交易日 (當天需 16:30 後) 的行情或法人還沒抓到，就補抓。
"""
import sys, os, datetime, traceback, zoneinfo
from . import db, sync
from .analysis import engine, backtest, ai
from .fetch.common import weekdays_back, iso
from . import build_static

def _taipei_now():
    return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Taipei"))

def missing_days(now=None):
    """尚未抓到行情或法人的交易日 (ISO 字串)。當天只在 16:30 後才算 (法人資料約 16:00 公布)。"""
    now = now or _taipei_now()
    today = now.date()
    out = []
    for d in weekdays_back(7, end=today):
        if d == today and now.time() < datetime.time(16, 30): continue
        if db.fetched("daily", iso(d)) not in ("ok", "holiday") or db.fetched("insti", iso(d)) not in ("ok", "holiday"):
            out.append(iso(d))
    return out

def decide_mode(mode, now=None):
    now = now or _taipei_now()
    if mode != "auto": return mode, []
    n = db.query("SELECT COUNT(DISTINCT date) n FROM daily")[0]["n"]
    miss = missing_days(now)
    if n < 30 or miss: return "full", miss
    return "news", []

def run(mode="auto"):
    db.init()
    now = _taipei_now()
    mode, miss = decide_mode(mode, now)
    today = now.strftime("%Y-%m-%d")
    print(f"cloud_sync mode={mode} taipei={now:%Y-%m-%d %H:%M} missing={miss}", flush=True)
    steps = [sync.sync_intl, sync.sync_news]
    if mode == "full":
        # 基本面 / 集保全市場檔 一天抓一次就夠 (重試補抓行情時不必重跑)
        if (db.get_meta("fundamentals_updated") or "")[:10] != today: steps.append(sync.sync_fundamentals)
        steps += [sync.sync_prices, sync.sync_insti]
        if (db.get_meta("tdcc_bulk_fetched") or "") != today: steps.append(sync.sync_tdcc)
    for st in steps:
        try:
            st()
            if st is sync.sync_tdcc: db.set_meta("tdcc_bulk_fetched", today)
        except Exception as e:
            print(f"{st.__name__} 失敗: {e}", flush=True); traceback.print_exc()
    d = engine.rebuild()
    if mode == "full":
        data_date = d.get("date")
        if db.get_meta("tdcc_candidates_for") != data_date:
            try:
                from .fetch import tdcc
                codes = engine.candidates_for_tdcc(70)
                tdcc.fetch_stocks_weeks(codes, weeks=2)
                db.set_meta("tdcc_candidates_for", data_date)
                engine.rebuild()
            except Exception as e: print("tdcc candidates", e, flush=True)
        if ((backtest.get() or {}).get("dates") or [None, None])[1] != data_date:   # 行情有新日期才重算回測
            try: backtest.run(); engine.rebuild()
            except Exception as e: print("backtest", e, flush=True)
    # AI 分析師 (需 API 金鑰)。每天最多兩次: 盤前 (07~09 點) 一次、收盤後資料到齊 (full) 一次
    slot = None
    if mode == "full" and d.get("date") == today: slot = f"{today}-pm"
    elif 7 <= now.hour <= 8: slot = f"{today}-am"
    if os.environ.get("ANTHROPIC_API_KEY") and slot and db.get_meta("ai_slot") != slot:
        try:
            ai._worker("api"); print("AI report:", (ai.report() or {}).get("generated"), flush=True)
            if ai.report() and not ai.state["error"]: db.set_meta("ai_slot", slot)
        except Exception as e: print("ai", e, flush=True)
    db.set_meta("last_sync", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    out = build_static.build()
    return out

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "auto")
