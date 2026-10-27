"""台股分析儀表板 API server (FastAPI)."""
import json, datetime, threading, time
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from . import db, sync, daytrade
from .config import STATIC_DIR, REC_MIN_DAY_LOTS
from .analysis import engine, market, ai, newsrules, backtest
from .analysis import technical as techmod
from .fetch import realtime
from fastapi import Body
from fastapi.responses import PlainTextResponse
import csv, io, socket, time as _time
import os

app = FastAPI(title="台股分析師")
from .config import APP_PASSWORD
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
import hashlib
_TOKEN = hashlib.sha256(("twsa:" + APP_PASSWORD).encode()).hexdigest()[:32] if APP_PASSWORD else ""
LOGIN_HTML = """<!doctype html><html lang=zh-Hant><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>台股分析師 登入</title>
<style>body{background:#0f1419;color:#e6edf3;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#171d26;padding:28px;border-radius:12px;border:1px solid #2a3441;width:300px}h1{font-size:18px;margin:0 0 14px}input{width:100%;padding:10px;border-radius:6px;border:1px solid #2a3441;background:#1e2632;color:#fff;font-size:16px;box-sizing:border-box}
button{width:100%;margin-top:12px;padding:10px;border:0;border-radius:6px;background:#1d4ed8;color:#fff;font-size:15px}p{color:#ff9a9c;font-size:13px}</style>
<form method=post action=/login><h1>📈 台股分析師</h1><input name=pw type=password placeholder="請輸入密碼" autofocus>{ERR}<button>登入</button></form>"""

@app.middleware("http")
async def _auth(request: Request, call_next):
    if APP_PASSWORD and not request.url.path.startswith(("/login", "/static/", "/manifest.json")):
        if request.cookies.get("twsa") != _TOKEN:
            if request.url.path.startswith("/api/"): return JSONResponse({"error": "unauthorized"}, status_code=401)
            return HTMLResponse(LOGIN_HTML.replace("{ERR}", ""))
    return await call_next(request)

@app.post("/login")
async def login(request: Request):
    form = await request.form()
    if APP_PASSWORD and form.get("pw") == APP_PASSWORD:
        r = RedirectResponse("/", status_code=303)
        r.set_cookie("twsa", _TOKEN, max_age=3600 * 24 * 365, httponly=True, samesite="lax")
        return r
    return HTMLResponse(LOGIN_HTML.replace("{ERR}", "<p>密碼錯誤</p>"))
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
db.init()

@app.on_event("startup")
def _startup():
    def boot():
        n = db.query("SELECT COUNT(DISTINCT date) n FROM daily")[0]["n"]
        last = db.get_meta("last_sync")
        if n < 30:
            sync.start("all")
        else:
            # refresh news + prices if the last sync is older than 30 minutes
            try: engine.rebuild()
            except Exception as e: print("rebuild", e)
            if not last or (datetime.datetime.now() - datetime.datetime.strptime(last, "%Y-%m-%d %H:%M")).total_seconds() > 1800:
                sync.start("all")
        if not os.environ.get("DAYTRADE_DISABLE"): daytrade.start()
    threading.Thread(target=boot, daemon=True).start()

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

_trading_cache = {"t": 0, "v": False}
def trading_now():
    if _time.time() - _trading_cache["t"] > 60:
        try: _trading_cache.update(t=_time.time(), v=realtime.is_trading_time())
        except Exception: _trading_cache.update(t=_time.time(), v=False)
    return _trading_cache["v"]

def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close(); return ip
    except Exception: return "127.0.0.1"

@app.get("/api/status")
def status():
    d = engine._cache["data"] or {}
    return {**sync.status, "trading": trading_now(), "last_sync": db.get_meta("last_sync"), "news_updated": db.get_meta("news_updated"),
            "data_date": d.get("date"), "n_stocks": len(d.get("stocks", {})), "n_dates": len(d.get("dates", [])),
            "tdcc_date": db.get_meta("tdcc_bulk_date"), "fund_updated": db.get_meta("fundamentals_updated"),
            "ai": {"running": ai.state["running"], "error": ai.state["error"], "mode": ai.available()}}

@app.post("/api/refresh")
def refresh(what: str = "news"):
    ok = sync.start(what)
    return {"started": ok, "status": sync.status}

@app.get("/api/overview")
def overview(min_lots: int = 1000):
    imp = market.intl_impact()
    tw = market.tw_summary()
    intl = db.get_meta("intl") or {}
    rows = db.query("SELECT id,source,category,title,link,published,summary,stocks,sentiment,tags FROM news ORDER BY published DESC LIMIT 300")
    for r in rows: _load_news(r)
    strong = sorted([r for r in rows if r["sentiment"] != 0], key=lambda r: (-abs(r["tags"].get("score", 0)), -r["published"]))
    bull = [r for r in strong if r["sentiment"] > 0][:8]
    bear = [r for r in strong if r["sentiment"] < 0][:8]
    latest = rows[:12]
    return {"impact": imp, "tw": tw, "intl": {k: v for k, v in intl.items() if k != "_updated"}, "bull_news": bull, "bear_news": bear,
            "latest_news": latest, "ai": ai.report(), "recommend": engine.recommend(10, min_lots),
            "foreign_sudden": engine.chips_list("foreign_sudden", 8, min_lots), "trust_sudden": engine.chips_list("trust_sudden", 8, min_lots),
            "data_date": (engine.get() or {}).get("date")}

def _load_news(r):
    try: r["stocks"] = json.loads(r["stocks"] or "[]")
    except Exception: r["stocks"] = []
    try: r["tags"] = json.loads(r["tags"] or "{}")
    except Exception: r["tags"] = {}
    r["time"] = datetime.datetime.fromtimestamp(r["published"]).strftime("%m/%d %H:%M")
    return r

@app.get("/api/news")
def news(cat: str = "", sent: str = "", q: str = "", tag: str = "", limit: int = 150):
    sql = "SELECT id,source,category,title,link,published,summary,stocks,sentiment,tags FROM news WHERE 1=1"
    p = []
    if cat: sql += " AND category=?"; p.append(cat)
    if sent == "bull": sql += " AND sentiment>0"
    elif sent == "bear": sql += " AND sentiment<0"
    if q: sql += " AND (title LIKE ? OR summary LIKE ? OR stocks LIKE ?)"; p += [f"%{q}%", f"%{q}%", f"%{q}%"]
    if tag: sql += " AND tags LIKE ?"; p.append(f"%{tag}%")
    sql += " ORDER BY published DESC LIMIT ?"; p.append(limit)
    rows = db.query(sql, p)
    names = {r["code"]: r["name"] for r in db.query("SELECT code,name FROM stocks")}
    for r in rows:
        _load_news(r)
        r["stock_names"] = [{"code": c, "name": names.get(c, c)} for c in r["stocks"]]
    return {"items": rows, "updated": db.get_meta("news_updated")}

def _dt_tag(items):
    return daytrade.tag_items(items)

@app.get("/api/recommend")
def recommend(limit: int = 40, min_lots: int = 1000):
    return {"items": _dt_tag(engine.recommend(limit, min_lots)), "date": engine.get().get("date"), "built": engine.get().get("built"), "min_day_lots": REC_MIN_DAY_LOTS}

@app.get("/api/flow")
def flow_api(limit: int = 40, min_lots: int = 1000):
    return engine.flow_list(limit, min_lots)

@app.get("/api/technical")
def technical(signal: str = "", limit: int = 80, min_lots: int = 1000):
    return {"items": _dt_tag(engine.technical_list(signal or None, limit, min_lots)), "factors": engine.get().get("factors", {}),
            "labels": techmod.SIGNAL_LABELS, "date": engine.get().get("date"), "min_day_lots": REC_MIN_DAY_LOTS}

@app.get("/api/chips")
def chips(kind: str = "foreign_sudden", limit: int = 60, min_lots: int = 0):
    return {"items": _dt_tag(engine.chips_list(kind, limit, min_lots)), "date": engine.get().get("date"), "insti_date": engine.get().get("insti_date"),
            "tdcc_date": db.get_meta("tdcc_bulk_date")}

@app.get("/api/stock/{code}")
def stock(code: str):
    d = engine.stock_detail(code)
    if len(d["bars"]) < 120 and not db.get_meta(f"yf_hist:{code}"):
        # extend history from Yahoo Finance (older bars only; local TWSE/TPEx data takes precedence)
        db.set_meta(f"yf_hist:{code}", datetime.date.today().isoformat())
        try:
            from .fetch import intl as intlf
            info = d["info"]
            rows = intlf.fetch_stock_history(code, info.get("market") or "TWSE")
            # 只補「比本機最早一天更早」的歷史；Yahoo 的休市日佔位列 (量 0、四價相同) 或比本機更新的日期一律不寫入，
            # 否則會把全市場的資料日推到假日、讓推薦/技術面全部消失
            first = d["bars"][0]["time"] if d["bars"] else "9999-99-99"
            rows = [r for r in rows if r[1] < first and (r[6] or 0) > 0]
            if rows:
                db.executemany("INSERT OR IGNORE INTO daily(code,date,open,high,low,close,volume,amount,txn) VALUES(?,?,?,?,?,?,?,?,?)", rows)
                d = engine.stock_detail(code)
        except Exception as e:
            print("yahoo fallback", code, e)
    for n in d["news"]:
        n["time"] = datetime.datetime.fromtimestamp(n["published"]).strftime("%m/%d %H:%M")
    if d["bars"]:
        wk = techmod.to_weekly(d["bars"])
        d["weekly"] = {"bars": wk, "ind": techmod.series([b["open"] for b in wk], [b["high"] for b in wk], [b["low"] for b in wk],
                                                           [b["close"] for b in wk], [b["volume"] for b in wk]) if len(wk) >= 30 else None}
    d["margin"] = db.query("SELECT date,fin_balance,fin_change,short_balance,short_change FROM margin WHERE code=? ORDER BY date DESC LIMIT 20", (code,))
    d["quote"] = realtime.quotes([code]).get(code) if realtime.is_trading_time() else None
    d["in_watchlist"] = bool(db.query("SELECT 1 FROM watchlist WHERE code=?", (code,)))
    return d

@app.get("/api/search")
def search(q: str = ""):
    return {"items": engine.search(q)}

@app.post("/api/ai")
def ai_start():
    return {"result": ai.start(), "mode": ai.available()}

@app.get("/api/ai")
def ai_get():
    return {"report": ai.report(), "running": ai.state["running"], "error": ai.state["error"], "mode": ai.available(), "started": ai.state["started"]}

@app.post("/api/tdcc_candidates")
def tdcc_candidates():
    """Fetch week-over-week 大戶 data for current candidates (background)."""
    if sync.status["running"]: return {"started": False}
    def job():
        from .fetch import tdcc
        codes = engine.candidates_for_tdcc(70)
        sync.status.update(running=True, task="tdcc_candidates", step="查詢集保大戶週變化", progress=0, total=len(codes))
        try:
            tdcc.fetch_stocks_weeks(codes, weeks=2, progress=lambda a, b: sync.status.update(progress=a, total=b))
            engine.rebuild()
        except Exception as e:
            sync.status["error"] = str(e)
        finally:
            sync.status["running"] = False
    threading.Thread(target=job, daemon=True).start()
    return {"started": True}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
_ext = os.path.join(os.path.dirname(STATIC_DIR), "chrome-extension")
if os.path.isdir(_ext): app.mount("/ext", StaticFiles(directory=_ext), name="ext")


@app.get("/api/rankings")
def rankings(kind: str = "gainers", limit: int = 50, min_lots: int = 0):
    return {"items": engine.rankings(kind, limit, min_lots), "date": engine.get().get("date")}

@app.get("/api/sectors")
def sectors():
    return {"items": engine.sectors(), "date": engine.get().get("date")}

@app.get("/api/backtest")
def backtest_get():
    return {"report": backtest.get()}

@app.post("/api/backtest")
def backtest_run(min_lots: int = 1000):
    return {"report": backtest.run(min_lots)}

@app.get("/api/watchlist")
def watchlist_get():
    items = engine.watchlist()
    q = realtime.quotes([i["code"] for i in items]) if items else {}
    for i in items: i["quote"] = q.get(i["code"])
    return {"items": items, "trading": realtime.is_trading_time()}

@app.post("/api/watchlist")
def watchlist_add(payload: dict = Body(...)):
    code = str(payload.get("code", "")).strip()
    if not db.query("SELECT 1 FROM stocks WHERE code=?", (code,)): return JSONResponse({"error": "找不到此代號"}, status_code=404)
    ex = db.query("SELECT * FROM watchlist WHERE code=?", (code,))
    row = ex[0] if ex else {"added": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "note": "", "alert_above": None, "alert_below": None}
    for k in ("note", "alert_above", "alert_below"):
        if k in payload: row[k] = payload[k] if payload[k] not in ("", None) else None
    db.executemany("INSERT OR REPLACE INTO watchlist(code,added,note,alert_above,alert_below) VALUES(?,?,?,?,?)",
                   [(code, row["added"], row["note"], row["alert_above"], row["alert_below"])])
    return {"ok": True}

@app.delete("/api/watchlist/{code}")
def watchlist_del(code: str):
    db.executemany("DELETE FROM watchlist WHERE code=?", [(code,)])
    return {"ok": True}

@app.get("/api/daytrade/live")
def daytrade_live(limit: int = 100, sort: str = "heat", direction: str = "", q: str = "", min_lots: int = 10000):
    """當沖雷達 (盤中每 5 秒更新): 振幅 / 時間量比 / 內外盤 / 1 分量 / VWAP / 五檔掛單差。min_lots: 成交張數門檻 (前一日或今日)。"""
    return daytrade.snapshot(min(max(limit, 1), 300), sort, direction, q.strip(), max(min_lots, 0))

@app.get("/api/daytrade/bars/{code}")
def daytrade_bars(code: str):
    d = daytrade.bars(code)
    return d if d else JSONResponse({"error": "not in pool"}, status_code=404)

@app.get("/api/daytrade/close")
def daytrade_close():
    """收盤後: 以隔日沖券商分點判斷隔日偏多 / 偏空候選。"""
    return daytrade.close_report()

@app.post("/api/daytrade/close")
def daytrade_close_build(force: int = 0):
    return {"started": daytrade.start_close_build(bool(force)), "status": daytrade.state["close"]}

@app.get("/api/daytrade/verify")
def daytrade_verify(days: int = 20):
    """名單驗證: 每日做多/做空名單 vs 隔一交易日實際走勢 (命中率、平均開盤→收盤幅度)。"""
    return daytrade.verify(min(max(days, 1), 60))

@app.get("/api/daytrade/status")
def daytrade_status():
    return {k: v for k, v in daytrade.state.items()}

@app.get("/api/quotes")
def quotes(codes: str = ""):
    lst = [c for c in codes.split(",") if c][:150]
    return {"quotes": realtime.quotes(lst), "trading": realtime.is_trading_time()}

EXPORT_COLS = ["code", "name", "market", "industry", "close", "chg", "lots", "avg20_lots", "amount", "vol_ratio", "total", "tech_score",
               "chip_score", "fund_score", "news_score", "foreign", "trust", "fin_change", "rev_yoy", "eps_q", "pe", "signals", "chip_signals"]
EXPORT_HEAD = ["代號", "名稱", "市場", "產業", "收盤", "漲跌%", "成交張", "20日均量", "成交金額", "量比", "總分", "技術", "籌碼", "基本", "新聞",
               "外資張", "投信張", "融資增減", "營收YoY", "EPS季", "本益比", "技術訊號", "籌碼訊號"]

@app.get("/api/export")
def export(what: str = "recommend", min_lots: int = 1000, signal: str = "", kind: str = "foreign_sudden"):
    items = {"recommend": lambda: engine.recommend(100, min_lots), "technical": lambda: engine.technical_list(signal or None, 200, min_lots),
             "chips": lambda: engine.chips_list(kind, 200, min_lots), "watchlist": engine.watchlist,
             "rankings": lambda: engine.rankings(kind, 100, min_lots)}.get(what, lambda: [])()
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(EXPORT_HEAD)
    for it in items:
        w.writerow(["、".join(it.get(c) or []) if isinstance(it.get(c), list) else ("" if it.get(c) is None else it.get(c)) for c in EXPORT_COLS])
    return PlainTextResponse("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f"attachment; filename={what}_{engine.get().get('date')}.csv"})


@app.get("/api/mobile")
def mobile(port: int = 8765):
    """手機連線資訊: 區網 IP、網址與 QR Code (SVG)。"""
    import segno
    ip = lan_ip(); url = f"http://{ip}:{port}/"
    svg = segno.make(url, error="m").svg_inline(scale=6, dark="#1b2430", light=None)
    return {"ip": ip, "url": url, "svg": svg, "host": socket.gethostname()}

@app.get("/manifest.json")
def manifest():
    return JSONResponse({"name": "台股分析師", "short_name": "台股分析師", "start_url": "/", "display": "standalone", "background_color": "#0f1419",
                         "theme_color": "#111820", "icons": [{"src": "/static/icon.png", "sizes": "128x128", "type": "image/png"},
                                                              {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"}]},
                        media_type="application/manifest+json")
