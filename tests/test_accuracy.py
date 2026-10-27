"""資料正確性 / 校正機制測試:
- 本機行情與 Yahoo Finance 交叉驗證 (需網路；取不到資料時跳過)
- 三大法人買賣超與證交所當日合計一致
- 依回測勝率的訊號權重校正邏輯
- 手機連線 / PWA 端點
"""
import sys, os, datetime
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import db
from app.analysis import engine, technical

def test_close_matches_yahoo_for_large_caps():
    import yfinance as yf
    mism = []
    checked = 0
    for code in ("2330", "2317", "2454", "2881"):
        local = db.query("SELECT date, close, volume FROM daily WHERE code=? ORDER BY date DESC LIMIT 15", (code,))
        if not local: continue
        try:
            df = yf.download(f"{code}.TW", period="2mo", interval="1d", progress=False, auto_adjust=False)
        except Exception:
            pytest.skip("Yahoo 無法連線")
        if df is None or df.empty: pytest.skip("Yahoo 無資料")
        if hasattr(df.columns, "levels"): df.columns = df.columns.get_level_values(0)
        y = {str(i.date()): float(r["Close"]) for i, r in df.iterrows()}
        for r in local:
            if r["date"] in y:
                checked += 1
                if abs(y[r["date"]] - r["close"]) / r["close"] > 0.002: mism.append((code, r["date"], r["close"], y[r["date"]]))
    assert checked >= 20, "交叉驗證樣本不足"
    assert not mism, f"收盤價與 Yahoo 不一致: {mism}"

def test_institutional_totals_consistent():
    """個股外資買賣超張數加總 × 收盤 應與證交所公布外資買賣超金額同號且量級相近 (誤差因價格用收盤近似)."""
    d = engine.get() or engine.rebuild()
    last = d["date"]
    tot = db.get_meta(f"insti_total:{last}")
    if not tot: pytest.skip("無當日法人合計資料")
    official = sum((tot.get(k) or 0) for k in tot if k.startswith("外資"))
    rows = db.query("SELECT i.code, i.foreign_net, d.close FROM insti i JOIN daily d ON d.code=i.code AND d.date=i.date JOIN stocks s ON s.code=i.code WHERE i.date=? AND s.market='TWSE'", (last,))
    est = sum(r["foreign_net"] * r["close"] for r in rows)
    # 官方合計含 ETF / 受益憑證等非個股；外資淨額接近零 (<100 億) 的日子個股加總可能異號，只在金額夠大時檢查
    if abs(official) < 100e8: pytest.skip(f"當日外資淨額僅 {official/1e8:.0f} 億，ETF 等非個股部位足以翻轉方向，略過")
    assert (est > 0) == (official > 0), f"方向不一致 est={est:.0f} official={official:.0f}"
    assert 0.5 < abs(est) / abs(official) < 2.0, f"量級差異過大 est={est/1e8:.1f}億 official={official/1e8:.1f}億"

def test_no_duplicate_or_future_dates():
    rows = db.query("SELECT code, COUNT(*) n, COUNT(DISTINCT date) d FROM daily GROUP BY code HAVING n<>d")
    assert not rows
    mx = db.query("SELECT MAX(date) m FROM daily")[0]["m"]
    assert mx <= datetime.date.today().isoformat()
    bad = db.query("SELECT COUNT(*) n FROM daily WHERE high < low OR close > high*1.0001 OR close < low*0.9999 OR close <= 0")[0]["n"]
    assert bad == 0, f"{bad} 筆 K 線 OHLC 不合理"

def test_signal_factor_logic():
    """勝率高於基準 → factor >1；低於 → <1；樣本不足 → 不調整；範圍 0.5~1.5."""
    saved = db.get_meta("backtest")
    try:
        db.set_meta("backtest", {"base": {"5": {"win": 50.0, "n": 1000}}, "signals": {
            "macd_low_cross": {"5": {"win": 62.0, "n": 500, "avg": 3.0}}, "pullback_ma20": {"5": {"win": 39.0, "n": 200, "avg": -0.8}},
            "ma60_up": {"5": {"win": 90.0, "n": 19, "avg": 1}}, "break20": {"5": {"win": 99.0, "n": 1000, "avg": 9}}, "_any": {"5": {"win": 55, "n": 9999}}}})
        f = engine.signal_factors()
        assert f["macd_low_cross"]["factor"] == 1.6 - 0.1 or abs(f["macd_low_cross"]["factor"] - 1.6) < 0.11  # 1 + 12/20 = 1.6 → clamp 1.5
        assert f["macd_low_cross"]["factor"] == 1.5 and f["pullback_ma20"]["factor"] == 0.5 and f["break20"]["factor"] == 1.5
        assert "ma60_up" not in f and "_any" not in f
    finally:
        db.set_meta("backtest", saved)

def test_penalty_and_adjusted_score_consistency():
    d = engine.get() or engine.rebuild()
    s = next(iter(d["stocks"].values()))
    t = s["tech"]
    assert "penalty" in t and t["penalty"] >= 0
    if d.get("factors") and "tech_score_raw" in t:
        assert 0 <= t["tech_score"] <= 100
        raw_sum = sum(x["w"] for x in t["signals"])
        assert t["tech_score_raw"] == max(0, min(100, raw_sum - t["penalty"]))

def test_mobile_and_manifest():
    from fastapi.testclient import TestClient
    from app import server
    with TestClient(server.app) as c:
        m = c.get("/api/mobile").json()
        assert m["url"].startswith("http://") and m["svg"].startswith("<svg") and m["ip"].count(".") == 3
        j = c.get("/manifest.json").json()
        assert j["display"] == "standalone" and j["icons"]
        assert c.get("/static/icon-512.png").content[:4] == b"\x89PNG"
        assert c.get("/api/status").json()["trading"] in (True, False)
