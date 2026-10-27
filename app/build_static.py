"""產生靜態網站 (GitHub Pages 用): 把所有 API 的結果預先輸出成 JSON 檔到 docs/。
用法: python -m app.build_static [輸出目錄]
"""
import os, sys, json, datetime, shutil, time
from . import db
from .config import BASE_DIR, STATIC_DIR, REC_MIN_DAY_LOTS
from .analysis import engine, market, ai, backtest, technical
from . import daytrade
from .analysis.technical import SIGNAL_LABELS

MIN_LOTS = [0, 500, 1000, 2000, 5000, 10000]
CHIP_KINDS = ["any_buy", "insti_top", "foreign_sudden", "trust_sudden", "both_buy", "foreign_streak", "trust_streak", "foreign_top", "trust_top",
              "foreign5", "trust5", "big_up", "big400_up", "fin_drop", "short_up"]
RANK_KINDS = ["gainers", "losers", "volume", "amount", "vol_ratio", "foreign", "foreign_sell", "trust", "fin_up"]

def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))

def _news_rows(limit=400):
    rows = db.query("SELECT id,source,category,title,link,published,summary,stocks,sentiment,tags FROM news ORDER BY published DESC LIMIT ?", (limit,))
    names = {r["code"]: r["name"] for r in db.query("SELECT code,name FROM stocks")}
    for r in rows:
        try: r["stocks"] = json.loads(r["stocks"] or "[]")
        except Exception: r["stocks"] = []
        try: r["tags"] = json.loads(r["tags"] or "{}")
        except Exception: r["tags"] = {}
        r["time"] = datetime.datetime.fromtimestamp(r["published"]).strftime("%m/%d %H:%M")
        r["stock_names"] = [{"code": c, "name": names.get(c, c)} for c in r["stocks"]]
    return rows

def build(out=None):
    t0 = time.time()
    out = out or os.path.join(BASE_DIR, "docs")
    api = os.path.join(out, "api")
    if os.path.isdir(api): shutil.rmtree(api)
    d = engine.rebuild()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # 靜態頁面本體
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(STATIC_DIR):
        shutil.copy(os.path.join(STATIC_DIR, f), os.path.join(out, "static_" + f) if False else os.path.join(out, f))
    html = open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8").read()
    html = html.replace('href="/static/', 'href="').replace('src="/static/', 'src="').replace('href="/manifest.json"', 'href="manifest.json"')
    html = html.replace('<script src="app.js"></script>', '<script>window.STATIC_MODE=true;</script>\n<script src="app.js"></script>')
    open(os.path.join(out, "index.html"), "w", encoding="utf-8").write(html)
    _dump(os.path.join(out, "manifest.json"), {"name": "台股分析師", "short_name": "台股分析師", "start_url": "./", "display": "standalone",
                                               "background_color": "#0f1419", "theme_color": "#111820",
                                               "icons": [{"src": "icon.png", "sizes": "128x128", "type": "image/png"}, {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]})
    open(os.path.join(out, ".nojekyll"), "w").close()
    # status
    _dump(os.path.join(api, "status.json"), {"running": False, "task": "", "step": "", "progress": 0, "total": 0, "log": [], "error": None,
          "last_sync": db.get_meta("last_sync"), "news_updated": db.get_meta("news_updated"), "data_date": d.get("date"), "n_stocks": len(d["stocks"]),
          "n_dates": len(d.get("dates", [])), "tdcc_date": db.get_meta("tdcc_bulk_date"), "fund_updated": db.get_meta("fundamentals_updated"),
          "insti_date": d.get("insti_date"), "min_day_lots": REC_MIN_DAY_LOTS,
          "trading": False, "ai": {"running": False, "error": None, "mode": "static"}, "built": now, "static": True,
          "repo": os.environ.get("GITHUB_REPOSITORY", ""), "workflow": "update.yml", "branch": os.environ.get("GITHUB_REF_NAME", "main")})
    # overview / recommend / technical / chips / rankings per min_lots
    news = _news_rows()
    strong = sorted([r for r in news if r["sentiment"] != 0], key=lambda r: (-abs(r["tags"].get("score", 0)), -r["published"]))
    imp = market.intl_impact(); tw = market.tw_summary(); intl = db.get_meta("intl") or {}
    rep = ai.report()
    for ml in MIN_LOTS:
        _dump(os.path.join(api, f"overview_{ml}.json"), {"impact": imp, "tw": tw, "intl": {k: v for k, v in intl.items() if k != "_updated"},
              "bull_news": [r for r in strong if r["sentiment"] > 0][:8], "bear_news": [r for r in strong if r["sentiment"] < 0][:8],
              "latest_news": news[:12], "ai": rep, "recommend": daytrade.tag_items(engine.recommend(10, ml)),
              "foreign_sudden": engine.chips_list("foreign_sudden", 8, ml), "trust_sudden": engine.chips_list("trust_sudden", 8, ml), "data_date": d.get("date")})
        _dump(os.path.join(api, f"flow_{ml}.json"), engine.flow_list(40, ml))
        _dump(os.path.join(api, f"recommend_{ml}.json"), {"items": daytrade.tag_items(engine.recommend(50, ml)), "date": d.get("date"), "built": d.get("built"), "min_day_lots": REC_MIN_DAY_LOTS})
        for sig in [""] + list(SIGNAL_LABELS):
            _dump(os.path.join(api, f"technical_{sig or 'all'}_{ml}.json"), {"items": daytrade.tag_items(engine.technical_list(sig or None, 100, ml)), "date": d.get("date"),
                                                                             "factors": d.get("factors", {}), "labels": SIGNAL_LABELS, "min_day_lots": REC_MIN_DAY_LOTS})
        for kind in CHIP_KINDS:
            _dump(os.path.join(api, f"chips_{kind}_{ml}.json"), {"items": daytrade.tag_items(engine.chips_list(kind, 80, ml)), "date": d.get("date"), "insti_date": d.get("insti_date"),
                                                                  "tdcc_date": db.get_meta("tdcc_bulk_date")})
        for kind in RANK_KINDS:
            _dump(os.path.join(api, f"rankings_{kind}_{ml}.json"), {"items": engine.rankings(kind, 60, ml), "date": d.get("date")})
    _dump(os.path.join(api, "sectors.json"), {"items": engine.sectors(), "date": d.get("date")})
    _dump(os.path.join(api, "backtest.json"), {"report": backtest.get()})
    # status 帶雲端這次嘗試建名單的結果 (例如「分點資料尚未公布」)，網頁才知道為什麼名單還是前一天的
    cst = {k: v for k, v in daytrade.state["close"].items() if k in ("step", "error", "date", "built")}; cst["running"] = False
    _dump(os.path.join(api, "daytrade_close.json"), {"report": db.get_meta("daytrade_close") or {}, "status": cst, "target_date": d.get("date")})
    try: ver = daytrade.verify(20)
    except Exception as e: print("daytrade verify", e); ver = {"days": [], "summary": {}}
    _dump(os.path.join(api, "daytrade_verify.json"), ver)
    _dump(os.path.join(api, "news.json"), {"items": news, "updated": db.get_meta("news_updated")})
    _dump(os.path.join(api, "ai.json"), {"report": rep, "running": False, "error": None, "mode": "static", "started": None})
    # stocks list (search) + per-stock detail
    stocks = db.query("SELECT code,name,market,industry FROM stocks ORDER BY code")
    for s in stocks:
        x = d["stocks"].get(s["code"])
        if x: s.update(close=x["close"], chg=x["chg"], total=x["total"])
    _dump(os.path.join(api, "stocks.json"), {"items": stocks})
    n = 0
    for s in stocks:
        if s["code"] not in d["stocks"]: continue
        det = engine.stock_detail(s["code"])
        for nw in det["news"]: nw["time"] = datetime.datetime.fromtimestamp(nw["published"]).strftime("%m/%d %H:%M")
        if det["bars"]:
            wk = technical.to_weekly(det["bars"])
            det["weekly"] = {"bars": wk, "ind": technical.series([b["open"] for b in wk], [b["high"] for b in wk], [b["low"] for b in wk], [b["close"] for b in wk], [b["volume"] for b in wk]) if len(wk) >= 30 else None}
        det["margin"] = db.query("SELECT date,fin_balance,fin_change,short_balance,short_change FROM margin WHERE code=? ORDER BY date DESC LIMIT 20", (s["code"],))
        det["quote"] = None; det["in_watchlist"] = False
        _dump(os.path.join(api, "stock", f"{s['code']}.json"), det)
        n += 1
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(out) for f in fs)
    print(f"build_static: {n} stocks, {total/1e6:.1f} MB in {time.time()-t0:.1f}s -> {out}", flush=True)
    return out

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
