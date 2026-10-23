"""綜合評分引擎: 技術面 + 籌碼面 + 基本面 + 新聞面 → 推薦清單；並提供個股明細。"""
import json, time, datetime
from collections import defaultdict
import numpy as np
from .. import db
from . import technical, chips, newsrules

_cache = {"built": 0, "data": None}

def _fund_score(f):
    if not f: return 0, []
    s, why = 0, []
    yoy, mom, cum = f.get("rev_yoy"), f.get("rev_mom"), f.get("rev_cum_yoy")
    eps = f.get("eps_q"); pe = f.get("pe")
    if yoy is not None:
        if yoy >= 50: s += 25; why.append(f"月營收年增{yoy:.0f}%")
        elif yoy >= 20: s += 18; why.append(f"月營收年增{yoy:.0f}%")
        elif yoy >= 5: s += 8
        elif yoy <= -20: s -= 15; why.append(f"月營收年減{abs(yoy):.0f}%")
    if mom is not None and mom >= 15: s += 8; why.append(f"營收月增{mom:.0f}%")
    if cum is not None and cum >= 20: s += 12; why.append(f"累計營收年增{cum:.0f}%")
    if eps is not None:
        if eps >= 3: s += 15; why.append(f"單季EPS {eps:.2f}元")
        elif eps > 0: s += 8
        else: s -= 15; why.append(f"單季EPS {eps:.2f}元(虧損)")
    if pe is not None and 0 < pe <= 15: s += 8; why.append(f"本益比{pe:.1f}倍偏低")
    elif pe is not None and pe > 60: s -= 5
    return max(0, min(100, s)), why

def _news_score(items):
    """items: list of (sentiment, score, title, published). Recent, stronger items weigh more."""
    if not items: return 0, []
    now = time.time(); s = 0; why = []
    for sent, sc, title, pub in items:
        age_d = max(0, (now - pub) / 86400)
        w = max(0.3, 1 - age_d / 5)
        s += max(-10, min(10, sc)) * w * 2
        if sent != 0 and len(why) < 3: why.append(("利多: " if sent > 0 else "利空: ") + title[:40])
    return max(-40, min(100, round(s))), why

def signal_factors():
    """依回測結果調整訊號權重: 5日勝率高於基準 → 加權 (最多 1.5x)，低於基準 → 減權 (最少 0.5x)。樣本 <100 不調整。"""
    rep = db.get_meta("backtest") or {}
    base = ((rep.get("base") or {}).get("5") or {}).get("win")
    out = {}
    if not base: return out
    for sid, v in (rep.get("signals") or {}).items():
        s5 = v.get("5")
        if sid.startswith("_") or not s5 or s5["n"] < 100: continue
        out[sid] = {"factor": round(max(0.5, min(1.5, 1 + (s5["win"] - base) / 20)), 2), "win": s5["win"], "n": s5["n"], "avg": s5["avg"], "base": base}
    return out

def rebuild():
    """Compute analysis for all stocks with data; cache result."""
    t0 = time.time()
    factors = signal_factors()
    stocks = {r["code"]: r for r in db.query("SELECT code,name,market,industry FROM stocks")}
    dates = [r["date"] for r in db.query("SELECT DISTINCT date FROM daily ORDER BY date")]
    if not dates:
        _cache.update(built=time.time(), data={"date": None, "stocks": {}, "dates": []}); return _cache["data"]
    last_date = dates[-1]
    daily = db.query("SELECT code,date,open,high,low,close,volume,amount FROM daily ORDER BY code,date")
    by = defaultdict(list)
    for r in daily: by[r["code"]].append(r)
    insti = db.query("SELECT code,date,foreign_net,trust_net,dealer_net FROM insti ORDER BY code,date")
    iby = defaultdict(list)
    for r in insti: iby[r["code"]].append(r)
    fund = {r["code"]: r for r in db.query("SELECT * FROM fundamentals")}
    mby = defaultdict(list)
    for r in db.query("SELECT code,date,fin_balance,fin_change,short_balance,short_change FROM margin ORDER BY code,date"): mby[r["code"]].append(r)
    news = db.query("SELECT stocks,sentiment,tags,title,published FROM news WHERE published > ?", (int(time.time()) - 5 * 86400,))
    nby = defaultdict(list)
    for r in news:
        try: codes = json.loads(r["stocks"] or "[]"); sc = json.loads(r["tags"] or "{}").get("score", 0)
        except Exception: codes, sc = [], 0
        for c in codes: nby[c].append((r["sentiment"], sc, r["title"], r["published"]))
    result = {}
    for code, rows in by.items():
        if rows[-1]["date"] != last_date or len(rows) < 30: continue
        o = [r["open"] or r["close"] for r in rows]; h = [r["high"] or r["close"] for r in rows]
        l = [r["low"] or r["close"] for r in rows]; c = [r["close"] for r in rows]; v = [r["volume"] or 0 for r in rows]
        try: tech = technical.analyze(o, h, l, c, v)
        except Exception as e:
            print("tech", code, e); tech = None
        if not tech: continue
        if factors:  # 依歷史勝率校正技術分數
            tech["tech_score_raw"] = tech["tech_score"]
            adj = sum(x["w"] * factors.get(x["id"], {}).get("factor", 1.0) for x in tech["signals"])
            tech["tech_score"] = int(max(0, min(100, round(adj - tech.get("penalty", 0)))))
            for x in tech["signals"]:
                f = factors.get(x["id"])
                if f: x["win5"] = f["win"]; x["base5"] = f["base"]
        amount = rows[-1]["amount"] or (rows[-1]["close"] * (rows[-1]["volume"] or 0))
        lots = (rows[-1]["volume"] or 0) / 1000
        avg20_lots = sum((r["volume"] or 0) for r in rows[-20:]) / 1000 / min(20, len(rows))
        avg20_amount = sum((r["amount"] or (r["close"] * (r["volume"] or 0))) for r in rows[-20:]) / min(20, len(rows))
        ch = chips.analyze(iby.get(code, []), rows[-1]["close"], rows[-1]["volume"]) if iby.get(code) else None
        mg = chips.margin_summary(mby.get(code, []), rows[-1]["volume"])
        if ch and mg:
            ch["margin"] = mg
            ch["signals"] += mg["signals"]
            ch["chip_score"] = max(0, min(100, ch["chip_score"] + sum(x["w"] for x in mg["signals"])))
        td = chips.tdcc_summary(code) if False else None  # filled lazily for candidates (see tdcc_enrich)
        fs, fwhy = _fund_score(fund.get(code))
        ns, nwhy = _news_score(nby.get(code, []))
        cs = ch["chip_score"] if ch else 0
        total = 0.40 * tech["tech_score"] + 0.30 * cs + 0.15 * fs + 0.15 * max(0, ns)
        if ns < -10: total -= 10
        if amount < 2e7: total *= 0.5  # illiquid
        if tech["close"] < 10: total *= 0.7
        st = stocks.get(code, {})
        result[code] = {"code": code, "name": st.get("name", code), "market": st.get("market", ""), "industry": st.get("industry", ""),
                        "close": tech["close"], "chg": tech["chg"], "amount": amount, "lots": round(lots), "avg20_lots": round(avg20_lots), "avg20_amount": avg20_amount, "vol_ratio": tech["vol_ratio"], "trend": tech["trend"],
                        "bias20": tech["bias20"], "tech": tech, "chips": ch, "fund": fund.get(code), "fund_score": fs, "fund_why": fwhy,
                        "news_score": ns, "news_why": nwhy, "news_n": len(nby.get(code, [])), "total": round(total, 1)}
    # TDCC enrich for the top candidates (cheap, from db)
    top = sorted(result.values(), key=lambda x: -x["total"])[:150]
    for s in top:
        td = chips.tdcc_summary(s["code"])
        s["tdcc"] = td
        tsig = chips.tdcc_signals(td)
        if tsig and s["chips"]:
            s["chips"]["signals"] += tsig
            s["chips"]["chip_score"] = max(0, min(100, s["chips"]["chip_score"] + sum(x["w"] for x in tsig)))
            s["total"] = round(s["total"] + 0.30 * sum(x["w"] for x in tsig), 1)
    data = {"date": last_date, "dates": dates[-60:], "stocks": result, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed": round(time.time() - t0, 1), "factors": factors}
    _cache.update(built=time.time(), data=data)
    print(f"engine.rebuild: {len(result)} stocks in {data['elapsed']}s", flush=True)
    return data

def get():
    if _cache["data"] is None: rebuild()
    return _cache["data"]

def candidates_for_tdcc(n=80):
    d = get()
    top = sorted(d["stocks"].values(), key=lambda x: -x["total"])[:n]
    chip_top = sorted((s for s in d["stocks"].values() if s["chips"]), key=lambda x: -x["chips"]["chip_score"])[:40]
    codes = []
    for s in top + chip_top:
        if s["code"] not in codes: codes.append(s["code"])
    return codes

def liquid(s, min_lots):
    return (s.get("avg20_lots") or 0) >= (min_lots or 0)

def recommend(limit=40, min_lots=1000):
    d = get()
    out = []
    for s in sorted(d["stocks"].values(), key=lambda x: -x["total"]):
        if s["total"] < 15: break
        if not liquid(s, min_lots): continue
        reasons = [x["label"] for x in s["tech"]["signals"] if x["w"] > 0][:5]
        if s["chips"]: reasons += [x["label"] for x in s["chips"]["signals"] if x["w"] > 0][:4]
        reasons += s["fund_why"][:2] + s["news_why"][:2]
        out.append({**_brief(s), "reasons": reasons, "risks": s["tech"]["notes"] + [x["label"] for x in (s["chips"]["signals"] if s["chips"] else []) if x["w"] < 0]})
        if len(out) >= limit: break
    return out

def _brief(s):
    return {"code": s["code"], "name": s["name"], "market": s["market"], "industry": s["industry"], "close": s["close"], "chg": s["chg"],
            "amount": s["amount"], "lots": s.get("lots"), "avg20_lots": s.get("avg20_lots"), "avg20_amount": s.get("avg20_amount"), "vol_ratio": s["vol_ratio"], "trend": s["trend"], "bias20": s["bias20"], "total": s["total"],
            "tech_score": s["tech"]["tech_score"], "chip_score": s["chips"]["chip_score"] if s["chips"] else 0, "fund_score": s["fund_score"],
            "news_score": s["news_score"], "news_n": s["news_n"], "foreign": s["chips"]["foreign"] if s["chips"] else None,
            "trust": s["chips"]["trust"] if s["chips"] else None, "foreign_streak": s["chips"]["foreign_streak"] if s["chips"] else 0,
            "trust_streak": s["chips"]["trust_streak"] if s["chips"] else 0, "signals": [x["label"] for x in s["tech"]["signals"]],
            "chip_signals": [x["label"] for x in s["chips"]["signals"]] if s["chips"] else [], "tdcc": s.get("tdcc"),
            "fin_change": (s["chips"].get("margin") or {}).get("fin_change") if s["chips"] else None,
            "fin_balance": (s["chips"].get("margin") or {}).get("fin_balance") if s["chips"] else None,
            "rev_yoy": (s["fund"] or {}).get("rev_yoy"), "eps_q": (s["fund"] or {}).get("eps_q"), "pe": (s["fund"] or {}).get("pe")}

def technical_list(signal=None, limit=80, min_lots=1000):
    d = get()
    rows = []
    for s in d["stocks"].values():
        if not liquid(s, min_lots): continue
        ids = [x["id"] for x in s["tech"]["signals"]]
        if signal and signal not in ids: continue
        if s["tech"]["tech_score"] < 20 or s["amount"] < 2e7: continue
        rows.append(_brief(s))
    rows.sort(key=lambda x: (-x["tech_score"], -x["amount"]))
    return rows[:limit]

def chips_list(kind="foreign_sudden", limit=60, min_lots=0):
    d = get()
    rows = []
    for s in d["stocks"].values():
        ch = s["chips"]
        if not ch or not liquid(s, min_lots): continue
        ids = [x["id"] for x in ch["signals"]]
        if kind == "foreign_top": key = ch["foreign"] * s["close"]
        elif kind == "trust_top": key = ch["trust"] * s["close"]
        elif kind == "foreign5": key = ch["foreign5"] * s["close"]
        elif kind == "trust5": key = ch["trust5"] * s["close"]
        elif kind == "big_up": key = (s.get("tdcc") or {}).get("d_big400") or 0
        elif kind in ids: key = ch["chip_score"]
        else: continue
        if key <= 0: continue
        rows.append({**_brief(s), "key": key})
    rows.sort(key=lambda x: -x["key"])
    return rows[:limit]

def stock_detail(code):
    d = get()
    rows = db.query("SELECT date,open,high,low,close,volume,amount FROM daily WHERE code=? ORDER BY date", (code,))
    st = db.query("SELECT * FROM stocks WHERE code=?", (code,))
    info = st[0] if st else {"code": code, "name": code, "market": "", "industry": ""}
    out = {"info": info, "analysis": None, "bars": [], "ind": None, "insti": [], "news": [], "fund": None, "tdcc": None}
    if rows and len(rows) >= 2:
        o = [r["open"] or r["close"] for r in rows]; h = [r["high"] or r["close"] for r in rows]
        l = [r["low"] or r["close"] for r in rows]; c = [r["close"] for r in rows]; v = [r["volume"] or 0 for r in rows]
        out["bars"] = [{"time": r["date"], "open": r["open"] or r["close"], "high": r["high"] or r["close"], "low": r["low"] or r["close"],
                        "close": r["close"], "volume": (r["volume"] or 0) / 1000} for r in rows]
        if len(rows) >= 30:
            out["ind"] = technical.series(o, h, l, c, v)
    s = d["stocks"].get(code)
    if s:
        out["analysis"] = {"tech": s["tech"], "chips": s["chips"], "fund_score": s["fund_score"], "fund_why": s["fund_why"],
                           "news_score": s["news_score"], "total": s["total"]}
    out["insti"] = db.query('SELECT date,foreign_net/1000 AS "foreign",trust_net/1000 AS trust,dealer_net/1000 AS dealer FROM insti WHERE code=? ORDER BY date DESC LIMIT 20', (code,))
    f = db.query("SELECT * FROM fundamentals WHERE code=?", (code,))
    out["fund"] = f[0] if f else None
    out["tdcc"] = chips.tdcc_summary(code)
    news = db.query("SELECT id,source,category,title,link,published,summary,sentiment,tags FROM news WHERE stocks LIKE ? ORDER BY published DESC LIMIT 15", (f'%"{code}"%',))
    for n in news:
        try: n["tags"] = json.loads(n["tags"])
        except Exception: n["tags"] = {}
    out["news"] = news
    return out

def search(q, limit=20):
    q = q.strip()
    if not q: return []
    rows = db.query("SELECT code,name,market,industry FROM stocks WHERE code LIKE ? OR name LIKE ? ORDER BY code LIMIT ?", (q + "%", "%" + q + "%", limit))
    d = get()
    for r in rows:
        s = d["stocks"].get(r["code"])
        if s: r.update(close=s["close"], chg=s["chg"], total=s["total"])
    return rows


def rankings(kind="gainers", limit=50, min_lots=0):
    d = get()
    keyf = {"gainers": lambda s: s["chg"], "losers": lambda s: -s["chg"], "volume": lambda s: s.get("lots") or 0,
            "amount": lambda s: s["amount"], "vol_ratio": lambda s: s["vol_ratio"] if (s.get("lots") or 0) >= 500 else -1,
            "foreign": lambda s: (s["chips"]["foreign"] * s["close"]) if s["chips"] else 0,
            "trust": lambda s: (s["chips"]["trust"] * s["close"]) if s["chips"] else 0,
            "foreign_sell": lambda s: (-s["chips"]["foreign"] * s["close"]) if s["chips"] else 0,
            "fin_up": lambda s: ((s["chips"].get("margin") or {}).get("fin_change") or 0) if s["chips"] else 0,
            }.get(kind, lambda s: s["chg"])
    rows = [s for s in d["stocks"].values() if liquid(s, min_lots) and s["amount"] >= 1e7]
    rows.sort(key=lambda s: -keyf(s))
    rows = [r for r in rows if keyf(r) > 0 or kind in ("gainers", "losers")][:limit]
    return [_brief(s) for s in rows]

def sectors():
    """產業族群漲跌: 成交金額加權漲幅、簡單平均、上漲/下跌家數、成交金額、外資合計."""
    d = get()
    agg = defaultdict(lambda: {"n": 0, "up": 0, "down": 0, "chg": 0.0, "amount": 0.0, "foreign": 0.0, "top": []})
    for s in d["stocks"].values():
        ind = s["industry"] or "其他"
        if ind in ("存託憑證", "管理股票", "91", "80"): continue
        a = agg[ind]; a["n"] += 1; a["chg"] += s["chg"]; a["amount"] += s["amount"]
        if s["chg"] > 0: a["up"] += 1
        elif s["chg"] < 0: a["down"] += 1
        if s["chips"]: a["foreign"] += s["chips"]["foreign"] * s["close"] * 1000
        a["top"].append((s["amount"], s["code"], s["name"], s["chg"]))
    out = []
    for ind, a in agg.items():
        if a["n"] < 3: continue
        w = sum(x[0] * x[3] for x in a["top"]) / a["amount"] if a["amount"] else 0
        top = sorted(a["top"], reverse=True)[:5]
        out.append({"industry": ind, "n": a["n"], "up": a["up"], "down": a["down"], "avg_chg": round(a["chg"] / a["n"], 2),
                    "w_chg": round(w, 2), "amount": a["amount"], "foreign_amt": a["foreign"],
                    "top": [{"code": t[1], "name": t[2], "chg": t[3]} for t in top]})
    out.sort(key=lambda x: -x["w_chg"])
    return out

def watchlist():
    d = get()
    rows = db.query("SELECT * FROM watchlist ORDER BY added")
    names = {r["code"]: r for r in db.query("SELECT code,name,market,industry FROM stocks")}
    out = []
    for r in rows:
        s = d["stocks"].get(r["code"])
        base = _brief(s) if s else {"code": r["code"], "name": names.get(r["code"], {}).get("name", r["code"]),
                                    "market": names.get(r["code"], {}).get("market", ""), "industry": "", "close": None, "chg": None,
                                    "signals": [], "chip_signals": [], "total": 0}
        out.append({**base, "added": r["added"], "note": r["note"], "alert_above": r["alert_above"], "alert_below": r["alert_below"]})
    return out
