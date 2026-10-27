"""資金流向：族群成交金額占大盤比重相對 20 日平均的增幅排名 (資金流入)、連續天數；熱門族群中仍在低點 (20 日乖離 ≤0) 的個股。

回測 (2026-07-20 ~ 10-22, 779 檔, avg20 ≥1000 張)：
- 族群資金流入排名前 5 連續 2 日以上 + 個股 20 日乖離 ≤0 → 5 日 62.8% / 10 日 64.6% (n≈1000)，基準 46.5% / 50.6%；
  乖離 <-5 更好 (67%)；當日 ≥1 萬張 78.7% / 70.5% (n=108/95)。同族群但乖離 >5 (已漲) 只有 48.9% / 40.2%。
- 只看單日資金流入 (不看連續) 效果弱很多 (44.5% / 57.3%)；資金流向加進推薦股綜合分數沒有幫助，獨立成一張名單才有效。
- 注意：樣本集中在 9 月半導體 / 光電多頭段；10 月弱勢月只與基準持平，沒有優勢。
"""
from collections import defaultdict
import numpy as np

EXCLUDE = {"", "其他", "ETF", "ETN", "受益證券", "存託憑證", "管理股票", "91", "80"}
TOP = 5           # 資金流入排名前幾名算熱門
STREAK = 2        # 連續幾日
LOOKBACK = 20


def industry_amounts(rows, industry_of):
    """daily 列 (code, date, amount, close, volume) → {date: {industry: amount}}。"""
    amt = defaultdict(lambda: defaultdict(float))
    for r in rows:
        g = industry_of.get(r["code"]) or ""
        if g in EXCLUDE: continue
        a = r["amount"] or ((r["close"] or 0) * (r["volume"] or 0))
        amt[r["date"]][g] += a or 0
    return amt


def rank_days(amt, lookback=LOOKBACK, top=TOP):
    """{date: {industry: amount}} → {date: {industry: {share, share_d, ratio, rank}}}，並算每個族群到該日為止連續幾日排名 ≤ top (streak)。
    share_d = 今日占比 - 近 lookback 日平均占比 (百分點)；用占比而不用絕對金額，大盤整體放量縮量才不會影響排名。"""
    dates = sorted(amt)
    out = {}
    streak = defaultdict(int)
    for j, d in enumerate(dates):
        if j < 5: continue
        hist = dates[max(0, j - lookback):j]
        tot = sum(amt[d].values()) or 1
        tot_h = {x: (sum(amt[x].values()) or 1) for x in hist}
        rec = {}
        for g, a in amt[d].items():
            share = a / tot * 100
            share_avg = float(np.mean([amt[x].get(g, 0) / tot_h[x] * 100 for x in hist]))
            avg_amt = float(np.mean([amt[x].get(g, 0) for x in hist])) or 1
            rec[g] = {"amount": a, "share": round(share, 2), "share_d": round(share - share_avg, 2), "ratio": round(a / avg_amt, 2)}
        order = sorted(rec, key=lambda g: -rec[g]["share_d"])
        for i, g in enumerate(order):
            rec[g]["rank"] = i + 1
            streak[g] = streak[g] + 1 if i + 1 <= top else 0
            rec[g]["streak"] = streak[g]
        out[d] = rec
    return out


def hot_industries(day_rec, top=TOP, min_streak=STREAK):
    """當日資金流入排名 ≤ top 且已連續 ≥ min_streak 日的族群 (依排名)。"""
    return [g for g, v in sorted(day_rec.items(), key=lambda kv: kv[1]["rank"]) if v["rank"] <= top and v["streak"] >= min_streak]


def pick(stocks, day_rec, top=TOP, min_streak=STREAK, max_bias=0.0, min_bias=-15.0):
    """stocks: iterable of dict (code, industry, bias20, ...)。回傳熱門族群內 20 日乖離在 (min_bias, max_bias] 的個股 (附族群資料)，依 (族群排名, 乖離) 排序。
    乖離 <-15 的是崩跌股不是低點 (回測 10 日 0/5)，排除。"""
    hot = set(hot_industries(day_rec, top, min_streak))
    out = []
    for s in stocks:
        g = s.get("industry") or ""
        if g not in hot: continue
        b = s.get("bias20")
        if b is None or b > max_bias or b < min_bias: continue
        f = day_rec[g]
        out.append({**s, "flow": {"industry": g, "rank": f["rank"], "streak": f["streak"], "share": f["share"], "share_d": f["share_d"], "ratio": f["ratio"]}})
    out.sort(key=lambda s: (s["flow"]["rank"], s["bias20"]))
    return out
