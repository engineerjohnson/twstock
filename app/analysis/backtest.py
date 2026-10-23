"""訊號勝率回測: 以本機歷史資料, 統計每個技術訊號出現後 N 日的報酬分布 (勝率 / 平均報酬 / 中位數)。
只看流動性足夠的股票 (近20日均量 >= min_lots)。"""
import time, datetime
from collections import defaultdict
import numpy as np
from .. import db
from . import technical

HORIZONS = (1, 3, 5, 10)

def run(min_lots=1000, max_stocks=800):
    t0 = time.time()
    daily = db.query("SELECT code,date,open,high,low,close,volume FROM daily ORDER BY code,date")
    by = defaultdict(list)
    for r in daily: by[r["code"]].append(r)
    stats = {sid: {h: [] for h in HORIZONS} for sid in technical.SIGNAL_LABELS}
    stats["_any"] = {h: [] for h in HORIZONS}       # 任一訊號
    stats["_score50"] = {h: [] for h in HORIZONS}   # 技術分 >= 50
    base = {h: [] for h in HORIZONS}                # 基準: 隨機任一天
    n_stocks = 0
    for code, rows in by.items():
        if len(rows) < 40: continue
        v = np.array([r["volume"] or 0 for r in rows], float)
        if v[-20:].mean() / 1000 < min_lots: continue
        n_stocks += 1
        if n_stocks > max_stocks: break
        o = [r["open"] or r["close"] for r in rows]; h = [r["high"] or r["close"] for r in rows]
        l = [r["low"] or r["close"] for r in rows]; c = np.array([r["close"] for r in rows], float)
        ind = technical.indicators(o, h, l, c, v)
        n = len(rows)
        for i in range(30, n - 1):
            s = technical.signals_at(ind, i)
            fwd = {hz: (c[i + hz] / c[i] - 1) * 100 for hz in HORIZONS if i + hz < n}
            if not fwd: continue
            for hz, ret in fwd.items(): base[hz].append(ret)
            if s["signals"]:
                for hz, ret in fwd.items(): stats["_any"][hz].append(ret)
            if s["score"] >= 50:
                for hz, ret in fwd.items(): stats["_score50"][hz].append(ret)
            for sid, _ in s["signals"]:
                for hz, ret in fwd.items(): stats[sid][hz].append(ret)
    def summ(arr):
        if not arr: return None
        a = np.array(arr)
        return {"n": int(len(a)), "win": round(float((a > 0).mean() * 100), 1), "avg": round(float(a.mean()), 2), "med": round(float(np.median(a)), 2)}
    out = {"signals": {}, "base": {hz: summ(base[hz]) for hz in HORIZONS}, "n_stocks": n_stocks,
           "dates": [daily[0]["date"] if daily else None, daily[-1]["date"] if daily else None],
           "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "elapsed": round(time.time() - t0, 1), "min_lots": min_lots}
    for sid, hs in stats.items():
        out["signals"][sid] = {"label": {"_any": "任一訊號", "_score50": "技術分≥50"}.get(sid) or technical.SIGNAL_LABELS[sid],
                               **{str(hz): summ(hs[hz]) for hz in HORIZONS}}
    db.set_meta("backtest", out)
    return out

def get():
    return db.get_meta("backtest")
