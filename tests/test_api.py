"""API 整合測試: 以實際資料庫 (需先同步過資料) 透過 FastAPI TestClient 驗證每個端點的狀態碼與回傳結構。"""
import sys, os, json
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fastapi.testclient import TestClient
from app import server, db
from app.analysis import engine

@pytest.fixture(scope="module")
def client():
    engine.rebuild()
    with TestClient(server.app) as c:
        yield c

def test_status(client):
    r = client.get("/api/status"); assert r.status_code == 200
    j = r.json(); assert "running" in j and j["n_stocks"] > 500 and j["data_date"]

def test_overview(client):
    j = client.get("/api/overview?min_lots=1000").json()
    assert j["impact"]["cls"] in ("bull", "bear", "neutral") and len(j["intl"]) >= 10
    assert len(j["recommend"]) <= 10 and all(r["avg20_lots"] >= 1000 for r in j["recommend"])
    assert all(n["sentiment"] > 0 for n in j["bull_news"]) and all(n["sentiment"] < 0 for n in j["bear_news"])
    assert j["tw"]["index"] and j["tw"]["insti"]

def test_news_filters(client):
    j = client.get("/api/news?sent=bull&limit=20").json()
    assert j["items"] and all(n["sentiment"] > 0 for n in j["items"])
    j = client.get("/api/news?q=台積電&limit=20").json()
    assert all("台積電" in n["title"] or "台積電" in (n["summary"] or "") or "2330" in n["stocks"] for n in j["items"])
    j = client.get("/api/news?tag=訂單/接單&limit=20").json()
    assert all("訂單/接單" in n["tags"]["topics"] for n in j["items"])

def test_recommend_sorted_and_liquidity(client):
    j = client.get("/api/recommend?limit=30&min_lots=2000").json()
    items = j["items"]; assert items
    assert all(items[i]["total"] >= items[i + 1]["total"] for i in range(len(items) - 1))
    assert all(r["avg20_lots"] >= 2000 and r["lots"] is not None for r in items)
    assert all(isinstance(r["reasons"], list) and r["reasons"] for r in items)
    j0 = client.get("/api/recommend?limit=30&min_lots=0").json()
    assert len(j0["items"]) >= len(items)

def test_technical_signal_filter(client):
    for sig in ("macd_low_cross", "kd_cross_low", "break20"):
        j = client.get(f"/api/technical?signal={sig}&limit=50").json()
        from app.analysis.technical import SIGNAL_LABELS
        assert all(SIGNAL_LABELS[sig] in r["signals"] for r in j["items"]), sig

def test_chips_kinds(client):
    for kind in ("foreign_sudden", "trust_sudden", "both_buy", "foreign_top", "big_up"):
        j = client.get(f"/api/chips?kind={kind}&limit=20"); assert j.status_code == 200
        items = j.json()["items"]
        if kind == "foreign_top": assert all(r["foreign"] > 0 for r in items) and all(items[i]["key"] >= items[i + 1]["key"] for i in range(len(items) - 1))
        if kind == "foreign_sudden": assert all(any("外資突然大買" in s for s in r["chip_signals"]) for r in items)

def test_stock_detail(client):
    j = client.get("/api/stock/2330").json()
    assert j["info"]["name"] == "台積電" and len(j["bars"]) >= 60 and j["ind"] and len(j["ind"]["ma20"]) == len(j["bars"])
    assert j["analysis"]["tech"]["close"] == j["bars"][-1]["close"]
    assert j["weekly"]["bars"] and j["weekly"]["bars"][-1]["close"] == j["bars"][-1]["close"]
    assert len(j["insti"]) >= 10 and "foreign" in j["insti"][0]
    assert isinstance(j["margin"], list) and "in_watchlist" in j
    assert client.get("/api/stock/9999999").status_code == 200  # unknown -> empty bars, not 500

def test_search(client):
    j = client.get("/api/search?q=台積").json(); assert any(i["code"] == "2330" for i in j["items"])
    j = client.get("/api/search?q=24").json(); assert all(i["code"].startswith("24") for i in j["items"])

def test_rankings_and_sectors(client):
    g = client.get("/api/rankings?kind=gainers&limit=10").json()["items"]
    assert g and all(g[i]["chg"] >= g[i + 1]["chg"] for i in range(len(g) - 1))
    l = client.get("/api/rankings?kind=losers&limit=10").json()["items"]
    assert l and all(l[i]["chg"] <= l[i + 1]["chg"] for i in range(len(l) - 1))
    v = client.get("/api/rankings?kind=volume&limit=10").json()["items"]
    assert v and all(v[i]["lots"] >= v[i + 1]["lots"] for i in range(len(v) - 1))
    s = client.get("/api/sectors").json()["items"]
    assert len(s) >= 15 and all(x["up"] + x["down"] <= x["n"] for x in s) and all(len(x["top"]) <= 5 for x in s)

def test_watchlist_crud(client):
    client.delete("/api/watchlist/2330")
    r = client.post("/api/watchlist", json={"code": "2330", "note": "測試", "alert_above": 2500, "alert_below": ""})
    assert r.status_code == 200
    j = client.get("/api/watchlist").json()
    it = [i for i in j["items"] if i["code"] == "2330"][0]
    assert it["note"] == "測試" and it["alert_above"] == 2500 and it["alert_below"] is None and it["name"] == "台積電"
    assert client.post("/api/watchlist", json={"code": "0000"}).status_code == 404
    assert client.delete("/api/watchlist/2330").json()["ok"]
    assert not [i for i in client.get("/api/watchlist").json()["items"] if i["code"] == "2330"]

def test_backtest_report(client):
    j = client.get("/api/backtest").json()["report"]
    assert j and j["base"]["5"]["n"] > 1000 and "macd_low_cross" in j["signals"]
    for sid, v in j["signals"].items():
        for hz in ("1", "3", "5", "10"):
            if v[hz]: assert 0 <= v[hz]["win"] <= 100 and v[hz]["n"] > 0

def test_export_csv(client):
    r = client.get("/api/export?what=recommend&min_lots=1000")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("代號,名稱") and len(lines) > 5 and len(lines[1].split(",")) >= 20

def test_quotes_endpoint_shape(client):
    j = client.get("/api/quotes?codes=2330,2454").json()
    assert "quotes" in j and "trading" in j
    for q in j["quotes"].values(): assert q["price"] is not None and "pct" in q

def test_ai_status(client):
    j = client.get("/api/ai").json(); assert "running" in j and "mode" in j

def test_static_pages(client):
    assert client.get("/").status_code == 200 and "台股分析師" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200 and client.get("/ext/popup.html").status_code == 200

def test_recommend_and_technical_require_10k_day_lots(client):
    """推薦股 / 技術面起漲: 前一交易日成交量需 >= 1 萬張 (REC_MIN_DAY_LOTS)。"""
    from app.config import REC_MIN_DAY_LOTS
    assert REC_MIN_DAY_LOTS == 10000
    for url in ("/api/recommend?limit=100&min_lots=0", "/api/technical?limit=200&min_lots=0", "/api/technical?signal=macd_cross&limit=200&min_lots=0"):
        j = client.get(url).json()
        assert j["min_day_lots"] == REC_MIN_DAY_LOTS
        assert all(r["lots"] >= REC_MIN_DAY_LOTS for r in j["items"]), url
    ov = client.get("/api/overview?min_lots=0").json()
    assert all(r["lots"] >= REC_MIN_DAY_LOTS for r in ov["recommend"])
    # 不限量時應該有股票成交量 < 1 萬張卻被排除 (證明過濾真的有作用)
    rk = client.get("/api/rankings?kind=volume&limit=500&min_lots=0").json()["items"]
    assert any(r["lots"] < REC_MIN_DAY_LOTS for r in rk)

def test_chips_any_buy_and_insti_top(client):
    j = client.get("/api/chips?kind=any_buy&limit=100&min_lots=0").json()
    assert j["insti_date"] and j["items"]
    for r in j["items"]:
        assert r["buyers"], r["code"]
        assert (r["foreign"] or 0) > 0 or (r["trust"] or 0) > 0 or (r["dealer"] or 0) > 0 or (r["insti_total"] or 0) > 0 or ((r.get("tdcc") or {}).get("d_big400") or 0) > 0
    assert all(j["items"][i]["key"] >= j["items"][i + 1]["key"] for i in range(len(j["items"]) - 1))
    t = client.get("/api/chips?kind=insti_top&limit=30&min_lots=0").json()["items"]
    assert t and all(r["insti_total"] > 0 for r in t) and all(t[i]["key"] >= t[i + 1]["key"] for i in range(len(t) - 1))
    assert all(abs(r["insti_total"] - ((r["foreign"] or 0) + (r["trust"] or 0) + (r["dealer"] or 0))) <= 2 for r in t)

def test_stock_yahoo_fallback_never_adds_newer_dates(client, monkeypatch):
    """個股頁向 Yahoo 補歷史時，比本機更新的日期或量 0 的假日佔位列不可寫入 (否則全市場資料日會被推到假日)。"""
    from app.fetch import intl as intlf
    last = db.query("SELECT MAX(date) m FROM daily")[0]["m"]
    # 找一檔本機 K 棒 < 120 根 (會觸發 Yahoo 補資料) 的股票
    code = db.query("SELECT code FROM daily GROUP BY code HAVING COUNT(*) BETWEEN 30 AND 119 ORDER BY code LIMIT 1")[0]["code"]
    first = db.query("SELECT MIN(date) m FROM daily WHERE code=?", (code,))[0]["m"]
    fake = [(code, "2019-01-02", 200, 201, 199, 200.5, 1000, None, None),          # 合法: 比本機更早且有量
            (code, "2019-01-03", 200, 200, 200, 200, 0, None, None),                # 量 0 佔位列
            (code, "2099-12-31", 999, 999, 999, 999, 5000, None, None)]             # 比本機更新
    monkeypatch.setattr(intlf, "fetch_stock_history", lambda c, market, period="1y": fake)
    db.executemany("DELETE FROM meta WHERE key=?", [(f"yf_hist:{code}",)])
    try:
        j = client.get(f"/api/stock/{code}").json()
        dates = [b["time"] for b in j["bars"]]
        assert "2099-12-31" not in dates and "2019-01-03" not in dates
        assert "2019-01-02" in dates and dates[0] <= first
        assert db.query("SELECT MAX(date) m FROM daily")[0]["m"] == last
    finally:
        con = db.connect(); con.execute("DELETE FROM daily WHERE code=? AND date IN ('2019-01-02','2019-01-03','2099-12-31')", (code,)); con.execute("DELETE FROM meta WHERE key=?", (f"yf_hist:{code}",)); con.commit(); con.close()
