"""國際市場 → 台股影響評估 (規則式) + 大盤摘要。"""
import json
from .. import db

def intl_impact():
    intl = db.get_meta("intl") or {}
    def g(t): return intl.get(t) or {}
    items, score = [], 0.0
    def add(t, w, label=None, inverse=False):
        nonlocal score
        x = g(t)
        if not x or x.get("pct") is None: return
        p = x["pct"] * (-1 if inverse else 1)
        s = p * w
        score += s
        items.append({"name": x.get("name", t), "ticker": t, "pct": x["pct"], "close": x["close"], "date": x.get("date"),
                      "impact": round(s, 2), "label": label or ""})
    add("^SOX", 0.55, "費半與台股電子高度連動")
    add("TSM", 0.6, "台積電ADR 直接影響權值股開盤")
    add("^IXIC", 0.35, "科技股風向")
    add("^GSPC", 0.25, "美股整體")
    add("^DJI", 0.1, "傳產/金融")
    add("NVDA", 0.2, "AI供應鏈指標")
    add("MU", 0.1, "記憶體族群")
    add("^N225", 0.15, "亞股連動")
    add("^KS11", 0.2, "韓股(半導體) 連動")
    add("^VIX", 0.05, "VIX 上升代表避險情緒升溫", inverse=True)
    add("USDTWD=X", 0.8, "台幣貶值(美元/台幣上升)常伴隨外資匯出", inverse=True)
    add("CL=F", 0.03, "油價上漲不利通膨/成本")
    add("^TNX", 0.1, "美債殖利率上升壓抑評價", inverse=True)
    score = max(-5, min(5, score))
    if score >= 1.5: view, cls = "偏多：國際市場強勢，台股開盤有望高開/走強", "bull"
    elif score >= 0.5: view, cls = "中性偏多：外圍小漲，台股可望平盤附近偏強", "bull"
    elif score <= -1.5: view, cls = "偏空：國際市場重挫，台股開盤恐大幅低開，留意權值股與電子股賣壓", "bear"
    elif score <= -0.5: view, cls = "中性偏空：外圍小跌，台股開盤偏弱震盪", "bear"
    else: view, cls = "中性：外圍平穩，台股以個股表現為主", "neutral"
    vix = g("^VIX").get("close")
    notes = []
    if vix and vix >= 25: notes.append(f"VIX {vix:.1f} 偏高，市場恐慌情緒濃，波動放大")
    tsm = g("TSM")
    if tsm.get("pct") is not None and abs(tsm["pct"]) >= 2:
        notes.append(f"台積電ADR {tsm['pct']:+.2f}%，台積電現股開盤預估同向反應 (ADR溢價變化亦需考量)")
    twd = g("USDTWD=X")
    if twd.get("pct") is not None and twd["pct"] >= 0.3: notes.append(f"美元/台幣 +{twd['pct']:.2f}% 台幣轉貶，外資可能偏向匯出")
    elif twd.get("pct") is not None and twd["pct"] <= -0.3: notes.append(f"台幣升值 {twd['pct']:.2f}%，外資資金可能回流")
    return {"score": round(score, 2), "view": view, "cls": cls, "items": items, "notes": notes, "updated": intl.get("_updated")}

def tw_summary():
    """大盤: 最近 5 個交易日指數與三大法人買賣超金額."""
    idx_rows = db.query("SELECT key,value FROM meta WHERE key LIKE 'index:%' ORDER BY key DESC LIMIT 10")
    tot_rows = db.query("SELECT key,value FROM meta WHERE key LIKE 'insti_total:%' ORDER BY key DESC LIMIT 10")
    idx = []
    for r in idx_rows:
        v = json.loads(r["value"]); d = r["key"].split(":")[1]
        tw = v.get("發行量加權股價指數") or {}
        idx.append({"date": d, "close": tw.get("close"), "change": tw.get("change"), "pct": tw.get("pct"),
                    "sectors": {k: v[k] for k in v if k != "發行量加權股價指數"}})
    tot = []
    for r in tot_rows:
        v = json.loads(r["value"]); d = r["key"].split(":")[1]
        f = sum((v.get(k) or 0) for k in v if k.startswith("外資"))
        t = v.get("投信") or 0
        dl = sum((v.get(k) or 0) for k in v if k.startswith("自營商"))
        tot.append({"date": d, "foreign": round(f / 1e8, 2), "trust": round(t / 1e8, 2), "dealer": round(dl / 1e8, 2), "total": round((f + t + dl) / 1e8, 2)})
    return {"index": idx, "insti": tot}
