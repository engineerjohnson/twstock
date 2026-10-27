"""單元測試: 技術指標正確性 (對照 pandas)、訊號偵測、籌碼訊號、新聞分類、解析函式。"""
import sys, os, math
import numpy as np
import pandas as pd
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.analysis import technical, chips, newsrules
from app.fetch.common import num, is_stock_code, roc_to_iso

rng = np.random.default_rng(42)

def synth(n=120, start=100.0, drift=0.0005, vol=0.02):
    c = start * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    o = c * (1 + rng.normal(0, 0.005, n)); h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.005, n))); l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.005, n)))
    v = rng.integers(500_000, 5_000_000, n).astype(float)
    return o, h, l, c, v

# ---------- indicators vs pandas ----------
def test_ema_matches_pandas():
    _, _, _, c, _ = synth()
    ours = technical.ema(c, 12)
    ref = pd.Series(c).ewm(span=12, adjust=False).mean().values
    assert np.allclose(ours, ref, atol=1e-9)

def test_sma_matches_pandas():
    _, _, _, c, _ = synth()
    ours = technical.sma(c, 20)
    ref = pd.Series(c).rolling(20).mean().values
    assert np.allclose(ours[19:], ref[19:], atol=1e-9) and np.isnan(ours[:19]).all()

def test_macd_matches_pandas():
    _, _, _, c, _ = synth()
    dif, dea, osc = technical.macd(c)
    s = pd.Series(c)
    ref_dif = (s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean())
    ref_dea = ref_dif.ewm(span=9, adjust=False).mean()
    assert np.allclose(dif, ref_dif.values, atol=1e-9)
    assert np.allclose(dea, ref_dea.values, atol=1e-9)
    assert np.allclose(osc, (ref_dif - ref_dea).values, atol=1e-9)

def test_kd_range_and_known_values():
    o, h, l, c, v = synth()
    k, d = technical.kd(h, l, c)
    assert ((k >= 0) & (k <= 100)).all() and ((d >= 0) & (d <= 100)).all()
    # 手算第一根: RSV = (c-l)/(h-l)*100, K = 50*2/3 + RSV/3
    rsv0 = (c[0] - l[0]) / (h[0] - l[0]) * 100
    assert math.isclose(k[0], 50 * 2 / 3 + rsv0 / 3, rel_tol=1e-9)

def test_rsi_matches_wilder():
    _, _, _, c, _ = synth()
    ours = technical.rsi(c, 14)
    diff = np.diff(c); up = np.where(diff > 0, diff, 0); dn = np.where(diff < 0, -diff, 0)
    au = pd.Series(up).ewm(alpha=1 / 14, adjust=False).mean(); ad = pd.Series(dn).ewm(alpha=1 / 14, adjust=False).mean()
    # Wilder with SMA seed differs from ewm seed for early bars; compare late bars only
    ref = 100 - 100 / (1 + au / ad)
    assert np.allclose(ours[80:], ref.values[79:], atol=0.5)

def test_bollinger_bands():
    o, h, l, c, v = synth()
    ind = technical.indicators(o, h, l, c, v)
    s = pd.Series(c)
    up = (s.rolling(20).mean() + 2 * s.rolling(20).std(ddof=0)).values
    assert np.allclose(ind["bb_up"][19:], up[19:], atol=1e-6)
    assert (ind["bb_up"][19:] > ind["bb_dn"][19:]).all()

# ---------- signals ----------
def test_macd_golden_cross_detected():
    # 製造: 先跌一段再快速上漲 -> DIF 由下往上穿越 MACD
    n = 80
    c = np.concatenate([np.linspace(100, 80, 50), np.linspace(80, 95, 30)])
    o = c.copy(); h = c * 1.01; l = c * 0.99; v = np.full(n, 1e6)
    ind = technical.indicators(o, h, l, c, v)
    found = False
    for i in range(30, n):
        ids = [s for s, _ in technical.signals_at(ind, i)["signals"]]
        if "macd_low_cross" in ids or "macd_cross" in ids: found = True; break
    assert found

def test_break20_and_volume_surge():
    n = 60
    c = np.full(n, 100.0); c[-1] = 110  # 最後一天突破 20 日高並大漲
    o = c.copy(); h = c * 1.001; l = c * 0.999; v = np.full(n, 1e6); v[-1] = 5e6
    a = technical.analyze(o, h, l, c, v)
    ids = [s["id"] for s in a["signals"]]
    assert "break20" in ids and "vol_surge" in ids
    assert a["vol_ratio"] > 4 and "已漲停,追高風險" in a["notes"]  # +10% 視為漲停 -> 扣分

def test_analyze_requires_30_bars_and_is_causal():
    o, h, l, c, v = synth(29)
    assert technical.analyze(o, h, l, c, v) is None
    o, h, l, c, v = synth(100)
    full = technical.indicators(o, h, l, c, v)
    part = technical.indicators(o[:70], h[:70], l[:70], c[:70], v[:70])
    # 第 69 根的訊號只依賴過去 -> 全序列與截斷序列結果一致
    assert technical.signals_at(full, 69)["signals"] == technical.signals_at(part, 69)["signals"]

def test_series_and_weekly():
    o, h, l, c, v = synth(50)
    s = technical.series(o, h, l, c, v)
    assert len(s["ma20"]) == 50 and s["ma20"][18] is None and s["ma20"][19] is not None
    bars = [{"time": f"2026-01-{d:02d}", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10} for d in range(5, 17)]
    wk = technical.to_weekly(bars)
    assert len(wk) == 2 and wk[0]["volume"] == 70 and wk[1]["volume"] == 50  # 1/5-1/11 (7天), 1/12-1/16 (5天)

# ---------- chips ----------
def test_foreign_sudden_buy_and_streak():
    rows = [{"date": f"d{i}", "foreign_net": 100_000, "trust_net": 0, "dealer_net": 0} for i in range(6)]
    rows.append({"date": "d6", "foreign_net": 5_000_000, "trust_net": 200_000, "dealer_net": 0})  # 5000張, 5日均100張 -> 50倍
    r = chips.analyze(rows, close=100, volume_shares=20_000_000)
    ids = [s["id"] for s in r["signals"]]
    assert "foreign_sudden" in ids and "foreign_streak" in ids and "both_buy" in ids
    assert r["foreign"] == 5000 and r["foreign_streak"] == 7 and r["chip_score"] > 30

def test_foreign_dump_penalty():
    rows = [{"date": "d0", "foreign_net": -3_000_000, "trust_net": 0, "dealer_net": 0}]
    r = chips.analyze(rows, close=100, volume_shares=10_000_000)
    assert any(s["id"] == "foreign_dump" and s["w"] < 0 for s in r["signals"]) and r["chip_score"] == 0

def test_margin_summary():
    rows = [{"date": f"d{i}", "fin_balance": 1000 + i * 100, "fin_change": 100, "short_balance": 10, "short_change": 0} for i in range(6)]
    m = chips.margin_summary(rows, 1e6)
    assert m["fin_change5"] == 500 and any(s["id"] == "fin_surge" for s in m["signals"])
    assert chips.margin_summary([], 0) is None

def test_tdcc_signals():
    s = {"d_big400": 1.2, "d_big1000": 0.8, "d_retail": -0.5}
    ids = [x["id"] for x in chips.tdcc_signals(s)]
    assert {"big400_up", "big1000_up", "retail_down"} <= set(ids)
    assert chips.tdcc_signals(None) == []

# ---------- news ----------
def test_news_sentiment():
    s, hb, hr = newsrules.score("友達搶到台積電訂單 預估明年EPS上升3倍 漲停")
    assert s > 0 and "訂單" in hb
    s2, _, hr2 = newsrules.score("台股重挫 外資賣超 砍單 跌停")
    assert s2 < 0 and "跌停" in hr2

def test_news_classify_highlights():
    item = {"title": "東台PCB鑽孔機接單滿載 營收年增 81% 目標價上看 60 元", "summary": "", "content": "", "stocks_hint": [], "keywords": []}
    c = newsrules.classify(item)
    assert c["sentiment"] == 1 and "訂單/接單" in c["tags"]
    assert any("年增" in h for h in c["highlights"]) and any("目標價" in h for h in c["highlights"])

# ---------- parsing ----------
def test_num_and_codes():
    assert num("1,234.5") == 1234.5 and num("--") is None and num("<p style='color:red'>+</p>") is None and num("+30.00") == 30
    assert is_stock_code("2330") and not is_stock_code("0050") and not is_stock_code("2881A") and not is_stock_code("00400A")
    assert roc_to_iso("115/10/22") == "2026-10-22" and roc_to_iso("1151022") == "2026-10-22"
