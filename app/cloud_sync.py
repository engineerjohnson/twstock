"""GitHub Actions 用：同步資料 (同步執行、不開伺服器) 後產生靜態網站。
用法:
  python -m app.cloud_sync news      # 新聞 + 國際行情 (每 2 小時)
  python -m app.cloud_sync full      # 行情/法人/融資券/基本面/集保 + 回測 + AI (每交易日收盤後)
  python -m app.cloud_sync auto      # 台北時間 15:30~18:00 視為 full，其餘 news
"""
import sys, os, datetime, traceback, zoneinfo
from . import db, sync
from .analysis import engine, backtest, ai
from . import build_static

def _taipei_now():
    return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Taipei"))

def run(mode="auto"):
    db.init()
    now = _taipei_now()
    if mode == "auto":
        mode = "full" if (now.weekday() < 5 and datetime.time(15, 30) <= now.time() <= datetime.time(18, 30)) else "news"
        # 若資料庫還沒有今天以前的完整資料 (例如第一次執行)，也跑 full
        n = db.query("SELECT COUNT(DISTINCT date) n FROM daily")[0]["n"]
        if n < 30: mode = "full"
    print(f"cloud_sync mode={mode} taipei={now:%Y-%m-%d %H:%M}", flush=True)
    steps = [sync.sync_intl, sync.sync_news]
    if mode == "full":
        steps += [sync.sync_fundamentals, sync.sync_prices, sync.sync_insti, sync.sync_tdcc]
    for st in steps:
        try: st()
        except Exception as e:
            print(f"{st.__name__} 失敗: {e}", flush=True); traceback.print_exc()
    engine.rebuild()
    if mode == "full":
        try:
            from .fetch import tdcc
            codes = engine.candidates_for_tdcc(70)
            tdcc.fetch_stocks_weeks(codes, weeks=2)
            engine.rebuild()
        except Exception as e: print("tdcc candidates", e, flush=True)
        try: backtest.run(); engine.rebuild()
        except Exception as e: print("backtest", e, flush=True)
    # AI 分析師 (僅在有 API 金鑰時；news 模式每次都跑會花錢，限制: full 模式或早上 07~09 點盤前各一次)
    if os.environ.get("ANTHROPIC_API_KEY") and (mode == "full" or 7 <= now.hour <= 8):
        try:
            ai._worker("api"); print("AI report:", (ai.report() or {}).get("generated"), flush=True)
        except Exception as e: print("ai", e, flush=True)
    db.set_meta("last_sync", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    out = build_static.build()
    return out

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "auto")
