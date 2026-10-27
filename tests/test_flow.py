from app.analysis import flow

def _amt():
    # 10 天：半導體前 8 天占比 30%，最後 2 天跳到 45% (資金流入)；金融相反；光電持平
    amt = {}
    for i in range(10):
        d = f"2026-10-{i + 1:02d}"
        semi = 45 if i >= 8 else 30 - i * 0.5; fin = 15 if i >= 8 else 30 + i * 0.5   # 前 8 天半導體占比緩降 (排名墊底)，最後 2 天跳升
        amt[d] = {"半導體": semi * 1e9, "金融保險": fin * 1e9, "光電": 40 * 1e9}
    return amt

def test_rank_days_share_delta_and_streak():
    r = flow.rank_days(_amt(), lookback=5, top=1)
    last = r["2026-10-10"]
    assert last["半導體"]["rank"] == 1 and last["半導體"]["share_d"] > 10 and last["半導體"]["streak"] == 2
    assert last["金融保險"]["rank"] == 3 and last["金融保險"]["share_d"] < -10 and r["2026-10-08"]["半導體"]["rank"] == 3
    assert r["2026-10-09"]["半導體"]["streak"] == 1 and r["2026-10-08"]["半導體"]["streak"] == 0

def test_pick_only_hot_and_low_bias():
    r = flow.rank_days(_amt(), lookback=5, top=1)
    stocks = [{"code": "2330", "industry": "半導體", "bias20": -3.0}, {"code": "2454", "industry": "半導體", "bias20": 6.0}, {"code": "3443", "industry": "半導體", "bias20": -22.0},
              {"code": "2881", "industry": "金融保險", "bias20": -8.0}, {"code": "3481", "industry": "光電", "bias20": -1.0}]
    p = flow.pick(stocks, r["2026-10-10"], top=1, min_streak=2)
    assert [s["code"] for s in p] == ["2330"] and p[0]["flow"]["rank"] == 1 and p[0]["flow"]["streak"] == 2
    assert flow.pick(stocks, r["2026-10-09"], top=1, min_streak=2) == []     # 只連 1 日不算

def test_industry_amounts_excludes_etf():
    rows = [{"code": "0050", "date": "d", "amount": 5e9, "close": 1, "volume": 1}, {"code": "2330", "date": "d", "amount": None, "close": 100, "volume": 1000}]
    amt = flow.industry_amounts(rows, {"0050": "ETF", "2330": "半導體"})
    assert dict(amt["d"]) == {"半導體": 100 * 1000}
