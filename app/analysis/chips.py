"""籌碼面: 外資 / 投信 / 自營 突然大買、連續買超、集保大戶(≥400張, ≥1000張)持股變化。"""
import numpy as np
from .. import db

def _streak(vals):
    """Consecutive positive (buy) or negative days from the latest bar. +n buying, -n selling."""
    n = 0
    for x in vals[::-1]:
        if x > 0 and n >= 0: n += 1
        elif x < 0 and n <= 0: n -= 1
        else: break
    return n

def analyze(insti_rows, close, volume_shares):
    """insti_rows: list of dicts sorted by date asc (foreign_net, trust_net, dealer_net in shares)."""
    if not insti_rows: return None
    f = np.array([r["foreign_net"] or 0 for r in insti_rows]) / 1000.0  # 張
    t = np.array([r["trust_net"] or 0 for r in insti_rows]) / 1000.0
    dl = np.array([r["dealer_net"] or 0 for r in insti_rows]) / 1000.0
    lots = (volume_shares or 0) / 1000.0
    price = close or 0
    sig = []
    def sudden(arr, name, min_amt):
        today = arr[-1]
        prev = np.abs(arr[-6:-1]) if len(arr) > 1 else np.array([0.0])
        base = max(prev.mean() if len(prev) else 0, 1.0)
        amt = today * price * 1000  # 元
        if today > 0 and amt >= min_amt and today >= 3 * base:
            return (f"{name}突然大買", today, round(today / base, 1), amt)
        return None
    s = sudden(f, "外資", 3e7)
    if s: sig.append({"id": "foreign_sudden", "label": f"{s[0]} {s[1]:,.0f}張 (近5日均量{s[2]}倍)", "w": 22})
    s = sudden(t, "投信", 1e7)
    if s: sig.append({"id": "trust_sudden", "label": f"{s[0]} {s[1]:,.0f}張 (近5日均量{s[2]}倍)", "w": 20})
    s = sudden(dl, "自營商", 2e7)
    if s: sig.append({"id": "dealer_sudden", "label": f"{s[0]} {s[1]:,.0f}張", "w": 6})
    fs, ts = _streak(f), _streak(t)
    if fs >= 3: sig.append({"id": "foreign_streak", "label": f"外資連{fs}日買超", "w": min(16, 6 + fs * 2)})
    if ts >= 3: sig.append({"id": "trust_streak", "label": f"投信連{ts}日買超", "w": min(16, 6 + ts * 2)})
    if f[-1] > 0 and t[-1] > 0: sig.append({"id": "both_buy", "label": "外資投信同步買超", "w": 10})
    f5, t5 = f[-5:].sum(), t[-5:].sum()
    f20, t20 = f[-20:].sum(), t[-20:].sum()
    if lots > 0 and f[-1] / lots >= 0.15: sig.append({"id": "foreign_ratio", "label": f"外資買超佔成交量{f[-1]/lots*100:.0f}%", "w": 8})
    if lots > 0 and t[-1] / lots >= 0.08: sig.append({"id": "trust_ratio", "label": f"投信買超佔成交量{t[-1]/lots*100:.0f}%", "w": 8})
    if f5 > 0 and f20 > 0 and f5 > f20 * 0.6: sig.append({"id": "foreign_accel", "label": "外資近5日加速買進", "w": 6})
    if f[-1] < 0 and f[-1] * price * 1000 <= -1e8: sig.append({"id": "foreign_dump", "label": f"外資大賣 {abs(f[-1]):,.0f}張", "w": -15})
    if t[-1] < 0 and t[-1] * price * 1000 <= -3e7: sig.append({"id": "trust_dump", "label": f"投信大賣 {abs(t[-1]):,.0f}張", "w": -12})
    score = max(0, min(100, sum(x["w"] for x in sig)))
    return {"foreign": round(f[-1]), "trust": round(t[-1]), "dealer": round(dl[-1]), "total": round(f[-1] + t[-1] + dl[-1]),
            "foreign5": round(f5), "trust5": round(t5),
            "foreign20": round(f20), "trust20": round(t20), "foreign_streak": fs, "trust_streak": ts,
            "signals": sig, "chip_score": score, "date": insti_rows[-1]["date"]}

def tdcc_summary(code):
    """大戶持股: latest two weeks, ≥1000張 (level 15) and ≥400張 (levels 12-15) percentages and holder counts."""
    rows = db.query("SELECT date,level,holders,pct FROM tdcc WHERE code=? ORDER BY date DESC, level", (code,))
    if not rows: return None
    by = {}
    for r in rows: by.setdefault(r["date"], {})[r["level"]] = r
    def valid(d):  # 減資/換發新股期間集保庫存會集中在單一帳戶 (100%)，視為無效快照
        lv = by[d]; holders = sum((lv.get(k, {}).get("holders", 0) or 0) for k in range(1, 16))
        return holders >= 50 and (lv.get(15, {}).get("pct", 0) or 0) < 99.5
    dates = [d for d in sorted(by) if valid(d)][-2:]
    if not dates: return None
    def agg(d):
        lv = by[d]
        big1000 = lv.get(15, {}).get("pct", 0) or 0
        big400 = sum((lv.get(k, {}).get("pct", 0) or 0) for k in (12, 13, 14, 15))
        retail = sum((lv.get(k, {}).get("pct", 0) or 0) for k in (1, 2, 3))  # <10張
        holders = sum((lv.get(k, {}).get("holders", 0) or 0) for k in range(1, 16))
        return {"date": d, "big1000": round(big1000, 2), "big400": round(big400, 2), "retail": round(retail, 2), "holders": holders}
    cur = agg(dates[-1])
    out = {"latest": cur}
    if len(dates) == 2:
        prev = agg(dates[0])
        out["prev"] = prev
        out["d_big1000"] = round(cur["big1000"] - prev["big1000"], 2)
        out["d_big400"] = round(cur["big400"] - prev["big400"], 2)
        out["d_retail"] = round(cur["retail"] - prev["retail"], 2)
        out["d_holders"] = cur["holders"] - prev["holders"]
    return out

def tdcc_signals(summary):
    sig = []
    if not summary or "d_big400" not in summary: return sig
    if summary["d_big400"] >= 0.5: sig.append({"id": "big400_up", "label": f"大戶(≥400張)持股週增{summary['d_big400']:+.2f}%", "w": 12})
    if summary["d_big1000"] >= 0.5: sig.append({"id": "big1000_up", "label": f"千張大戶持股週增{summary['d_big1000']:+.2f}%", "w": 14})
    if summary["d_retail"] <= -0.3 and summary["d_big400"] > 0: sig.append({"id": "retail_down", "label": "散戶減少、籌碼集中", "w": 6})
    if summary["d_big400"] <= -1.0: sig.append({"id": "big400_down", "label": f"大戶持股週減{summary['d_big400']:+.2f}%", "w": -10})
    return sig


def margin_summary(rows, volume_shares):
    """融資餘額變化 (張): rows sorted asc with fin_balance/fin_change/short_balance/short_change."""
    if not rows: return None
    last = rows[-1]
    fin, chg = last["fin_balance"] or 0, last["fin_change"] or 0
    chg5 = sum((r["fin_change"] or 0) for r in rows[-5:])
    sig = []
    prev = max(fin - chg5, 1)
    if fin > 0 and chg5 / prev >= 0.15 and chg5 >= 300:
        sig.append({"id": "fin_surge", "label": f"融資5日大增{chg5:,.0f}張(+{chg5 / prev * 100:.0f}%)，散戶追價須留意", "w": -4})
    elif fin > 0 and chg5 / prev <= -0.10 and chg5 <= -300:
        sig.append({"id": "fin_drop", "label": f"融資5日減{abs(chg5):,.0f}張，籌碼洗清", "w": 6})
    sh = last["short_balance"] or 0; shc = last["short_change"] or 0
    if sh > 0 and shc >= 200 and shc / max(sh - shc, 1) >= 0.2:
        sig.append({"id": "short_up", "label": f"融券大增{shc:,.0f}張(軋空潛力)", "w": 3})
    return {"fin_balance": round(fin), "fin_change": round(chg), "fin_change5": round(chg5), "short_balance": round(sh),
            "short_change": round(shc), "date": last["date"], "signals": sig}
