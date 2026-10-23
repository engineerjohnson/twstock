"""技術面分析: MA / MACD / KD / RSI / 布林 / 量能, 以及「準備起漲」訊號偵測與評分。
indicators() 一次算完整個序列；signals_at(i) 只看第 i 根以前的資料 (因果), 因此可用於回測。"""
import numpy as np

SIGNAL_LABELS = {
    "macd_low_cross": "MACD低檔黃金交叉", "macd_cross": "MACD黃金交叉", "osc_turn": "MACD柱狀體翻揚", "osc_positive": "OSC由負翻正",
    "kd_cross_low": "KD低檔黃金交叉", "kd_cross": "KD黃金交叉", "ma20_break": "帶量站上月線", "ma20_up": "站上月線", "ma60_up": "站上季線",
    "bull_align_new": "均線轉多頭排列", "bull_align": "多頭排列", "ma_rising": "月季線上揚", "break60": "突破60日新高", "break20": "突破20日新高",
    "vol_surge": "爆量上漲", "vol_up": "量增價漲", "pullback_ma20": "回測月線不破反彈", "rsi_rebound": "RSI超賣反彈", "bb_breakout": "布林收斂後向上突破",
}

def ema(x, n):
    out = np.empty_like(x, dtype=float); k = 2.0 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)): out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out

def sma(x, n):
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out

def macd(close, fast=12, slow=26, sig=9):
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, sig)
    return dif, dea, dif - dea

def kd(high, low, close, n=9, m1=3, m2=3):
    k = np.full(len(close), 50.0); d = np.full(len(close), 50.0)
    for i in range(len(close)):
        lo = low[max(0, i - n + 1):i + 1].min(); hi = high[max(0, i - n + 1):i + 1].max()
        rsv = 50.0 if hi == lo else (close[i] - lo) / (hi - lo) * 100
        k[i] = (k[i - 1] if i else 50.0) * (m1 - 1) / m1 + rsv / m1
        d[i] = (d[i - 1] if i else 50.0) * (m2 - 1) / m2 + k[i] / m2
    return k, d

def rsi(close, n=14):
    out = np.full(len(close), np.nan)
    if len(close) <= n: return out
    diff = np.diff(close); up = np.where(diff > 0, diff, 0.0); dn = np.where(diff < 0, -diff, 0.0)
    au = up[:n].mean(); ad = dn[:n].mean()
    out[n] = 100 - 100 / (1 + au / ad) if ad else 100
    for i in range(n + 1, len(close)):
        au = (au * (n - 1) + up[i - 1]) / n; ad = (ad * (n - 1) + dn[i - 1]) / n
        out[i] = 100 - 100 / (1 + au / ad) if ad else 100
    return out

def indicators(o, h, l, c, v):
    c = np.asarray(c, float); h = np.asarray(h, float); l = np.asarray(l, float); v = np.asarray(v, float); o = np.asarray(o, float)
    dif, dea, osc = macd(c)
    k, d = kd(h, l, c)
    ma5, ma10, ma20, ma60 = sma(c, 5), sma(c, 10), sma(c, 20), sma(c, 60)
    vma5, vma20 = sma(v, 5), sma(v, 20)
    r = rsi(c)
    std20 = np.full(len(c), np.nan)
    for i in range(19, len(c)): std20[i] = c[i - 19:i + 1].std()
    with np.errstate(invalid="ignore", divide="ignore"):
        bw = (4 * std20) / ma20
    return {"ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "vma5": vma5, "vma20": vma20, "dif": dif, "dea": dea, "osc": osc,
            "k": k, "d": d, "rsi": r, "bb_up": ma20 + 2 * std20, "bb_dn": ma20 - 2 * std20, "bw": bw,
            "_o": o, "_h": h, "_l": l, "_c": c, "_v": v}

def _cross_up(a, b, i, within=2):
    """a crossed above b at some bar in (i-within, i]."""
    for j in range(i, max(0, i - within), -1):
        if j >= 1 and a[j] > b[j] and a[j - 1] <= b[j - 1]: return True
    return False

def _nan(x): return x is None or (isinstance(x, float) and np.isnan(x))

def signals_at(ind, i):
    """Signals [(id, weight)], score, notes, trend for bar i using only bars <= i."""
    c, h, l, v = ind["_c"], ind["_h"], ind["_l"], ind["_v"]
    ma5, ma10, ma20, ma60 = ind["ma5"], ind["ma10"], ind["ma20"], ind["ma60"]
    dif, dea, osc, k, d, r = ind["dif"], ind["dea"], ind["osc"], ind["k"], ind["d"], ind["rsi"]
    sig = []
    vma20 = ind["vma20"][i]
    vr = v[i] / vma20 if not _nan(vma20) and vma20 > 0 else 1.0
    chg = (c[i] / c[i - 1] - 1) * 100 if i >= 1 and c[i - 1] else 0.0
    bias20 = (c[i] / ma20[i] - 1) * 100 if not _nan(ma20[i]) and ma20[i] else 0.0
    if _cross_up(dif, dea, i):
        sig.append(("macd_low_cross", 20) if dif[i] < 0 else ("macd_cross", 14))  # 低檔黃金交叉回測勝率最高 (~63%)
    if i >= 3 and osc[i] > osc[i - 1] > osc[i - 2] and osc[i - 2] < 0 and osc[i] > osc[i - 3]:
        sig.append(("osc_turn", 8))
    if i >= 1 and osc[i] > 0 and osc[i - 1] <= 0 and not any(s[0].startswith("macd") for s in sig):
        sig.append(("osc_positive", 8))
    if _cross_up(k, d, i) and k[i] < 65:
        sig.append(("kd_cross_low", 14) if k[i] < 40 else ("kd_cross", 10))
    if _cross_up(c, ma20, i) and vr >= 1.3: sig.append(("ma20_break", 16))
    elif _cross_up(c, ma20, i): sig.append(("ma20_up", 8))
    if _cross_up(c, ma60, i): sig.append(("ma60_up", 10))
    aligned = not _nan(ma20[i]) and ma5[i] > ma10[i] > ma20[i]
    was_aligned = i >= 5 and not _nan(ma20[i - 5]) and ma5[i - 5] > ma10[i - 5] > ma20[i - 5]
    if aligned and not was_aligned: sig.append(("bull_align_new", 14))
    elif aligned: sig.append(("bull_align", 5))
    if not _nan(ma20[i]) and i >= 5 and ma20[i] > ma20[i - 5] and not _nan(ma60[i]) and ma60[i] > ma60[i - 5]:
        sig.append(("ma_rising", 5))
    if i >= 20 and c[i] > h[i - 20:i].max():
        sig.append(("break60", 16) if i >= 60 and c[i] > h[i - 60:i].max() else ("break20", 12))
    if vr >= 2 and chg > 0: sig.append(("vol_surge", 12))
    elif vr >= 1.5 and chg > 0: sig.append(("vol_up", 6))
    if (not _nan(ma60[i]) and c[i] > ma60[i] and not _nan(ma20[i]) and i >= 5 and not np.isnan(ma20[i - 5:i]).any()
            and min(c[i - 5:i] / ma20[i - 5:i]) <= 1.01 and c[i] > ma20[i] and chg > 0):
        sig.append(("pullback_ma20", 4))  # 回測勝率偏低 (約39%), 降低權重
    if not _nan(r[i]) and i >= 3 and r[i] > 40 and np.nanmin(r[i - 3:i]) < 35: sig.append(("rsi_rebound", 10))
    bw = ind["bw"]
    if i >= 21 and not _nan(bw[i - 1]) and not np.isnan(bw[max(0, i - 60):i]).all() \
            and bw[i - 1] < np.nanpercentile(bw[max(0, i - 60):i], 25) and c[i] > ind["bb_up"][i - 1]:
        sig.append(("bb_breakout", 12))
    raw = sum(w for _, w in sig)
    notes, penalty = [], 0
    if bias20 > 15: penalty += 15; notes.append(f"乖離過大({bias20:.0f}%)")
    if chg >= 9.5: penalty += 15; notes.append("已漲停,追高風險")
    elif chg >= 7: penalty += 6; notes.append("單日漲幅已大")
    if not _nan(r[i]) and r[i] > 80: penalty += 8; notes.append("RSI過熱")
    if not _nan(ma60[i]) and c[i] < ma60[i] and not any(s[0] == "ma60_up" for s in sig): penalty += 5
    score = max(0, min(100, raw - penalty))
    trend = "多頭" if aligned else ("空頭" if (not _nan(ma20[i]) and ma5[i] < ma10[i] < ma20[i]) else "盤整")
    return {"signals": sig, "score": score, "notes": notes, "trend": trend, "vr": vr, "chg": chg, "bias20": bias20, "penalty": penalty}

def label(sid, vr=None):
    if sid == "vol_surge" and vr is not None: return f"爆量上漲(量{vr:.1f}倍)"
    if sid == "vol_up" and vr is not None: return f"量增價漲({vr:.1f}倍)"
    return SIGNAL_LABELS.get(sid, sid)

def analyze(o, h, l, c, v):
    """Latest-bar analysis dict (needs >= 30 bars)."""
    n = len(c)
    if n < 30: return None
    ind = indicators(o, h, l, c, v)
    i = n - 1
    s = signals_at(ind, i)
    c = ind["_c"]; h = ind["_h"]; l = ind["_l"]; v = ind["_v"]
    return {"close": float(c[i]), "chg": round(s["chg"], 2), "vol": float(v[i]), "vol_ratio": round(s["vr"], 2), "bias20": round(s["bias20"], 2),
            "ma5": _f(ind["ma5"][i]), "ma10": _f(ind["ma10"][i]), "ma20": _f(ind["ma20"][i]), "ma60": _f(ind["ma60"][i]),
            "dif": _f(ind["dif"][i]), "dea": _f(ind["dea"][i]), "osc": _f(ind["osc"][i]), "k": _f(ind["k"][i]), "d": _f(ind["d"][i]), "rsi": _f(ind["rsi"][i]),
            "signals": [{"id": sid, "label": label(sid, s["vr"]), "w": w} for sid, w in s["signals"]], "notes": s["notes"],
            "tech_score": s["score"], "penalty": s["penalty"], "trend": s["trend"],
            "high20": float(h[max(0, i - 20):i + 1].max()), "low20": float(l[max(0, i - 20):i + 1].min())}

def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)

def series(o, h, l, c, v):
    """Full indicator arrays for charting (lists with None for NaN)."""
    ind = indicators(o, h, l, c, v)
    return {k: [_f(x) for x in arr] for k, arr in ind.items() if not k.startswith("_") and k != "bw"}

def to_weekly(bars):
    """Aggregate daily bars (dicts: time/open/high/low/close/volume) into weekly bars (ISO week, time = first day)."""
    import datetime
    out, cur, key = [], None, None
    for b in bars:
        d = datetime.date.fromisoformat(b["time"]); k = d.isocalendar()[:2]
        if k != key:
            if cur: out.append(cur)
            cur = dict(b); key = k
        else:
            cur["high"] = max(cur["high"], b["high"]); cur["low"] = min(cur["low"], b["low"]); cur["close"] = b["close"]
            cur["volume"] += b["volume"]
    if cur: out.append(cur)
    return out
