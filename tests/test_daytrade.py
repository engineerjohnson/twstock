"""當沖雷達: 內外盤分類、1 分 K 累積、指標、隔日沖券商判斷、分點頁面解析 (純函式測試) + API 結構。"""
import sys, os, datetime, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import daytrade
from app.fetch import broker, realtime

def q(price, vol, bid, ask, t="09:05:10", prev=100.0, o=100.0, h=None, l=None):
    return {"price": price, "volume": vol, "bid": bid, "ask": ask, "time": t, "prev": prev, "open": o, "high": h or max(price, o), "low": l or min(price, o),
            "pct": round((price / prev - 1) * 100, 2), "bid_vol": 100, "ask_vol": 50, "limit_up": 110.0, "limit_down": 90.0, "live": True}

def test_classify_outer_inner():
    last = {"price": 100.0, "bid": 99.5, "ask": 100.0}
    assert daytrade.classify(100.0, 10, last) == (10, 0)     # 成交在賣價 = 外盤 (買方主動)
    assert daytrade.classify(99.5, 10, last) == (0, 10)      # 成交在買價 = 內盤
    last = {"price": 100.0, "bid": 99.0, "ask": 101.0}
    assert daytrade.classify(100.5, 10, last) == (10, 0)     # 介於買賣價之間: 價漲 → 外盤
    assert daytrade.classify(99.5, 10, last) == (0, 10)
    assert daytrade.classify(100.0, 10, last) == (5, 5)      # 無法判斷平分
    assert daytrade.classify(100.0, 0, last) == (0, 0)

def test_update_state_bars_and_vwap():
    s = daytrade._new_state({"code": "9999", "name": "測試", "lots": 1000, "avg20_lots": 2000, "amount": 1e8})
    daytrade.update_state(s, q(100.0, 500, 99.5, 100.0, "09:05:03"))      # 第一筆: 500 張未分類
    assert s["unclassified"] == 500 and s["outer"] == 0 and len(s["bars"]) == 1
    daytrade.update_state(s, q(100.0, 600, 99.5, 100.5, "09:05:08"))      # +100 張成交在前一刻賣價 → 外盤
    daytrade.update_state(s, q(99.5, 650, 99.0, 99.5, "09:06:02"))        # +50 張成交在前一刻買價 → 內盤, 新的一分鐘
    assert s["outer"] == 100 and s["inner"] == 50 and len(s["bars"]) == 2
    assert s["bars"][0]["v"] == 100 and s["bars"][0]["outer"] == 100 and s["bars"][1]["inner"] == 50
    vwap = s["vwap_num"] / s["vwap_den"]
    assert abs(vwap - (100 * 100 + 99.5 * 50) / 150) < 1e-9
    m = daytrade.metrics(s, frac=0.1)
    assert m["outer_ratio"] == 66.7 and m["net5"] == 50 and m["vol1"] == 50 and m["vwap"] == round(vwap, 2)
    assert m["vol_ratio"] == round(650 / (2000 * 0.1), 2) and m["est_day_lots"] == 6500
    assert m["amp"] > 0 and m["direction"] in ("bull", "bear", "flat") and isinstance(m["signals"], list)

def test_stale_snapshot_ignored_and_old_book_not_used():
    """MIS 不同節點回傳新舊不一的快照: 比上一筆舊的要忽略 (不可倒帶/重複計算)；間隔太久時不用舊買賣價判斷。"""
    s = daytrade._new_state({"code": "9999", "name": "測試", "lots": 1000, "avg20_lots": 2000, "amount": 1e8})
    daytrade.update_state(s, q(100.0, 500, 99.5, 100.0, "09:05:03"))
    daytrade.update_state(s, q(100.0, 600, 99.5, 100.5, "09:05:08"))   # +100 外盤
    daytrade.update_state(s, q(100.0, 500, 99.5, 100.0, "09:05:03"))   # 舊節點的舊快照 → 忽略
    assert s["last"]["v"] == 600 and s["outer"] == 100 and s["volume"] == 600
    daytrade.update_state(s, q(100.0, 600, 99.5, 100.5, "09:05:08"))   # 同一筆再來一次 → dv=0 不重複計算
    assert s["outer"] == 100 and s["inner"] == 0
    # 兩分鐘後才有新快照: 價跌到 99，前一快照的買賣價已過時 → 只看價格方向 (跌 → 內盤)，不因 99 <= 舊買價就誤判
    daytrade.update_state(s, q(100.4, 800, 100.0, 100.5, "09:07:30"))  # 介於舊買賣價之間但 gap>20s → 價漲 → 外盤
    assert s["outer"] == 300
    daytrade.update_state(s, q(99.0, 900, 98.5, 99.0, "09:09:40"))
    assert s["inner"] == 100 and s["outer"] == 300
    assert daytrade.classify(100.0, 10, {"price": 101.0, "bid": 99.0, "ask": 100.0}, stale=True) == (0, 10)   # 舊賣價=100 但 stale → 看方向: 跌 → 內盤

def test_metrics_direction_bull():
    s = daytrade._new_state({"code": "9999", "name": "測試", "lots": 1000, "avg20_lots": 1000, "amount": 1e8})
    daytrade.update_state(s, q(101.0, 100, 100.5, 101.0, "09:01:00", o=100.0, h=101.0, l=99.8))
    for i in range(1, 6):
        daytrade.update_state(s, q(101.0 + i * 0.5, 100 + i * 200, 101.0 + i * 0.5 - 0.5, 101.0 + i * 0.5, f"09:0{i + 1}:00", o=100.0, h=101.0 + i * 0.5, l=99.8))
    m = daytrade.metrics(s, frac=0.05)
    assert m["direction"] == "bull" and m["bull"] >= 3 and m["outer_ratio"] == 100.0 and m["vwap_pos"] > 0 and m["pos"] == 1.0
    assert any("爆量" in x for x in m["signals"]) and "近高點" in m["signals"]

def test_session_fraction():
    d = datetime.datetime(2026, 10, 27)
    assert daytrade.session_fraction(d.replace(hour=8, minute=59)) == 1 / 270
    assert abs(daytrade.session_fraction(d.replace(hour=11, minute=15)) - 0.5) < 1e-9
    assert daytrade.session_fraction(d.replace(hour=14)) == 1.0

SAMPLE_HTML = """<table><tr><td class="t10">台光電(2383)主力進出明細</td><div class="t11">近一日　最後更新：2026/10/22</div>
<TR><TD class="t2">買超券商</TD><TD class="t2">買進</TD><TD class="t2">賣出</TD><TD class="t2">買超</TD><TD class="t2">佔成交比重</TD><TD class="t2">賣超券商</TD><TD class="t2">買進</TD><TD class="t2">賣出</TD><TD class="t2">賣超</TD><TD class="t2">佔成交比重</TD></TR>
<TR><TD class="t4t1"><a href="x">凱基-台北</a></TD><TD class="t3n1">1,845</TD><TD class="t3n1">606</TD><TD class="t3n1">1,239</TD><TD class="t3n1">5.03%</TD>
<TD class="t4t1"><a href="x">凱基-信義</a></TD><TD class="t3n1">9</TD><TD class="t3n1">253</TD><TD class="t3n1">244</TD><TD class="t3n1">5.14%</TD></TR>
<TR><TD class="t4t1"><a href="x">美林</a></TD><TD class="t3n1">224</TD><TD class="t3n1">9</TD><TD class="t3n1">215</TD><TD class="t3n1">4.53%</TD>
<TD class="t4t1"><a href="x">台灣摩根士丹利</a></TD><TD class="t3n1">187</TD><TD class="t3n1">408</TD><TD class="t3n1">221</TD><TD class="t3n1">4.65%</TD></TR>
<TR><TD class="t3n1">合計買超張數</TD><TD class="t3n1">1,062</TD><TD class="t3n1">合計賣超張數</TD><TD class="t3n1">753</TD></TR></table>"""

def test_parse_broker_html():
    r = broker.parse_broker_html(SAMPLE_HTML)
    assert r["date"] == "2026-10-22" and r["buy_total"] == 1062 and r["sell_total"] == 753
    assert [b["broker"] for b in r["buy"]] == ["凱基-台北", "美林"] and r["buy"][0]["net"] == 1239 and r["buy"][0]["pct"] == 5.03
    assert [s["broker"] for s in r["sell"]] == ["凱基-信義", "台灣摩根士丹利"] and r["sell"][0]["net"] == -244

def test_is_overnight_exact_match():
    pats = ["凱基台北", "群益金鼎大安", "美林", "摩根大通", "統一士林"]
    assert broker.is_overnight("凱基-台北", pats) and broker.is_overnight("群益金鼎-大安", pats) and broker.is_overnight("群益-大安", pats)
    assert broker.is_overnight("美林", pats) and broker.is_overnight("摩根大通", pats)
    assert not broker.is_overnight("凱基-台北法人", pats) and not broker.is_overnight("統一", pats) and not broker.is_overnight("凱基證券", pats)
    assert not broker.is_overnight("台灣摩根士丹利", pats) and not broker.is_overnight("", pats)

def _st(**kw):
    base = {"code": "9999", "name": "測試", "close": 109.5, "open": 103, "high": 110, "low": 102, "prev": 100.0, "chg": 9.5, "amp": 8.0, "lots": 10000, "vol_ratio": 3.0, "dt_ratio": 45.0}
    base.update(kw); return base

def test_judge_short_when_overnight_broker_dominates():
    flows = [{"broker": "凱基-台北", "buy": 900, "sell": 100, "net": 800, "pct": 8.0}, {"broker": "元大-台北", "buy": 300, "sell": 50, "net": 250, "pct": 2.5},
             {"broker": "富邦-建國", "buy": 200, "sell": 0, "net": 200, "pct": 2.0}, {"broker": "國泰-台北", "buy": 10, "sell": 600, "net": -590, "pct": 5.9}]
    j = daytrade.judge(_st(chg=5.0, close=105.0, high=106, low=101), flows, ["凱基台北", "富邦建國"], market_pct=0.5)
    assert j["verdict"] == "short" and j["on_buy"] == 1000 and j["on_buy_pct"] == 10.0 and j["top1_overnight"] and j["dominance"] == 3.2
    assert j["buyers"][0]["overnight"] and not j["buyers"][1]["overnight"] and j["sellers"][0]["broker"] == "國泰-台北"
    assert any("隔日沖券商合計買超" in r for r in j["reasons"]) and any("第 1 名" in r for r in j["reasons"]) and not j["limit_up"]   # 109.5 不是漲停 (漲停 110)

def test_judge_long_after_overnight_dump():
    flows = [{"broker": "凱基-台北", "buy": 50, "sell": 1000, "net": -950, "pct": 9.5}, {"broker": "元大-台北", "buy": 400, "sell": 50, "net": 350, "pct": 3.5}]
    j = daytrade.judge(_st(chg=1.2, close=104, high=105, low=100, prev_chg=5.0), flows, ["凱基台北"])
    assert j["verdict"] == "watch" and j["on_sell"] == 950 and j["on_sell_pct"] == 9.5 and any("倒出" in r for r in j["reasons"])   # 回測無優勢 → 只觀察

def test_judge_long_strong_without_overnight():
    flows = [{"broker": "元大-台北", "buy": 500, "sell": 50, "net": 450, "pct": 4.5}, {"broker": "國泰-敦北", "buy": 400, "sell": 50, "net": 350, "pct": 3.5},
             {"broker": "富邦-台北", "buy": 300, "sell": 0, "net": 300, "pct": 3.0}]
    j = daytrade.judge(_st(chg=6.0, close=106, high=106.5, low=101), flows, ["凱基台北"])
    assert j["verdict"] == "watch" and j["on_buy"] == 0 and j["buy5_pct"] == 11.0 and any("大盤" in r for r in j["reasons"])   # 沒給大盤漲跌 → 只觀察

def test_judge_short_weak_stock_heavy_selling():
    flows = [{"broker": "元大-台北", "buy": 100, "sell": 900, "net": -800, "pct": 8.0}, {"broker": "凱基-台北", "buy": 50, "sell": 500, "net": -450, "pct": 4.5},
             {"broker": "國泰-敦北", "buy": 300, "sell": 50, "net": 250, "pct": 2.5}]
    j = daytrade.judge(_st(chg=-5.0, close=95, open=100.5, high=101, low=94.5, vol_ratio=1.6), flows, ["凱基台北"])
    assert j["verdict"] == "watch" and j["sell5_pct"] == 12.5 and j["on_sell"] == 450 and any("帶量下跌" in r for r in j["reasons"])   # 回測 44% → 不列做空
    j2 = daytrade.judge(_st(chg=-5.0, close=99.5, open=100.5, high=101, low=94.5, vol_ratio=1.6), flows, ["凱基台北"])   # 收在高檔 (拉尾盤) → 不算
    assert not any("帶量下跌" in r for r in j2["reasons"])

def test_limit_up_price_and_bigcap_flag():
    assert daytrade.limit_up_price(100) == 110.0 and daytrade.limit_up_price(60) == 66.0 and daytrade.limit_up_price(23.5) == 25.85 and daytrade.limit_up_price(1420) == 1560.0
    # 大型股 (成交額 >= 30 億) 的美林/摩根大通不算隔日沖：合計與第一名旗標都要一致，不能只因它是買超第一就做空
    flows = [{"broker": "美林", "buy": 2000, "sell": 0, "net": 2000, "pct": 4.0}, {"broker": "元大-台北", "buy": 500, "sell": 100, "net": 400, "pct": 0.8}]
    j = daytrade.judge(_st(chg=6.0, close=106, open=101, high=106.5, low=100.5, lots=50000, amount=5e9), flows, ["美林"], market_pct=0.5)
    assert j["on_buy"] == 0 and not j["top1_overnight"] and not j["buyers"][0]["overnight"]   # 旗標與合計一致 (做空與否由成因規則決定)
    j = daytrade.judge(_st(chg=6.0, close=106, open=101, high=106.5, low=100.5, lots=50000, amount=1e9), flows, ["美林"], market_pct=0.5)   # 小型股照算
    assert j["verdict"] == "short" and j["on_buy"] == 2000

def test_taifex_parsers():
    from app.fetch import taifex
    lst = [{"DispCName": "臺指現貨", "SymbolID": "TXF-S", "CLastPrice": "46096.23", "CRefPrice": "46041.43", "COpenPrice": "46211.20", "CHighPrice": "", "CLowPrice": "", "CDiff": "", "CDiffRate": "", "CTotalVolume": "", "CTime": "133325", "CDate": "20261027"},
           {"DispCName": "臺指期116", "SymbolID": "TXFK6-F", "CLastPrice": "46081.00", "CRefPrice": "46234.00", "COpenPrice": "46505.00", "CHighPrice": "46846", "CLowPrice": "46050", "CTotalVolume": "100353", "CTime": "134459", "CDate": "20261027"},
           {"DispCName": "臺指期126", "SymbolID": "TXFL6-F", "CLastPrice": "46000", "CRefPrice": "46150", "COpenPrice": "46400", "CHighPrice": "46700", "CLowPrice": "45990", "CTotalVolume": "900", "CTime": "134459", "CDate": "20261027"},
           {"DispCName": "臺指期116W5", "SymbolID": "TXFK6W5-F", "CLastPrice": "46090", "CRefPrice": "46240", "COpenPrice": "46510", "CHighPrice": "46850", "CLowPrice": "46055", "CTotalVolume": "200000", "CTime": "134459", "CDate": "20261027"}]
    q = taifex.parse_quote_list(lst)
    assert q["spot"]["last"] == 46096.23 and q["near"]["symbol"] == "TXFK6-F" and q["near"]["pct"] == -0.33 and q["near"]["open_pct"] == 0.59   # 週契約不算近月
    csvtxt = "交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段\n" \
             "2026/10/01,TX,202610  ,48398,48719,48168,48685,355,0.73%,34458,48698,107607,48685,48689,48946,39852,,一般\n" \
             "2026/10/01,TX,202610  ,48320,48592,48158,48298,-32,-0.07%,28717,-,-,48280,48297,48946,39852,,盤後\n" \
             "2026/10/01,TX,202611  ,48484,48866,48330,48858,364,0.75%,363,48858,1507,48843,48850,49090,44435,,一般\n" \
             "2026/10/01,TX,202610W1,48400,48700,48100,48600,300,0.6%,99999,-,-,-,-,-,-,,一般\n"
    h = taifex.parse_history_csv(csvtxt)
    assert h["2026-10-01"]["day"]["c"] == 48685 and h["2026-10-01"]["day"]["month"] == "202610" and h["2026-10-01"]["night"]["c"] == 48298

def test_parse_broker_rows_with_one_side_empty():
    html = ("<table><TR><TD>凱基-台北</TD><TD>300</TD><TD>10</TD><TD>290</TD><TD>2.9%</TD><TD>國泰-敦南</TD><TD>5</TD><TD>400</TD><TD>395</TD><TD>3.95%</TD></TR>"
            "<TR><TD></TD><TD></TD><TD></TD><TD></TD><TD></TD><TD>富邦-建國</TD><TD>0</TD><TD>120</TD><TD>120</TD><TD>1.2%</TD></TR></table><div>最後更新：2026/10/22</div>")
    p = daytrade.broker.parse_broker_html(html)
    assert p["date"] == "2026-10-22" and [b["broker"] for b in p["buy"]] == ["凱基-台北"] and [s["broker"] for s in p["sell"]] == ["國泰-敦南", "富邦-建國"] and p["sell"][1]["net"] == -120

def test_export_import_history_roundtrip(tmp_path, monkeypatch):
    store = {"daytrade_close:2026-10-01": {"date": "2026-10-01", "short": []}, "index:2026-10-01": {"pct": 0.5}, "other": 1}
    monkeypatch.setattr(daytrade.db, "query", lambda sql, args=(): [{"key": k, "value": json.dumps(v)} for k, v in store.items() if any(k.startswith(p) for p in ("daytrade_close:", "index:", "tx_futures:")) and (not args or k.startswith(args[0].rstrip("%")))])
    p = tmp_path / "seed.json"
    assert daytrade.export_history(str(p)) == 2
    monkeypatch.setattr(daytrade.db, "query", lambda sql, args=(): [{"key": "index:2026-10-01"}])
    added = {}
    monkeypatch.setattr(daytrade.db, "set_meta", lambda k, v: added.__setitem__(k, v))
    assert daytrade.import_history(str(p)) == 1 and list(added) == ["daytrade_close:2026-10-01"]

def test_rank_from_flows_excludes_foreign_houses_and_sorts():
    rows = [{"code": "1101", "name": "台泥", "broker": "摩根大通", "net": 4000, "buy": 4000, "sell": 0, "close": 50, "prev": 48, "lots": 100000},
            {"code": "1101", "name": "台泥", "broker": "凱基-台北", "net": 500, "buy": 600, "sell": 100, "close": 50, "prev": 48, "lots": 100000},
            {"code": "4526", "name": "東台", "broker": "凱基-台北", "net": 1600, "buy": 1600, "sell": 0, "close": 30, "prev": 28, "lots": 57000},
            {"code": "4526", "name": "東台", "broker": "元大-土城永寧", "net": -200, "buy": 0, "sell": 200, "close": 30, "prev": 28, "lots": 57000},
            {"code": "9999", "name": "倒貨", "broker": "凱基-台北", "net": -900, "buy": 0, "sell": 900, "close": 10, "prev": 10, "lots": 20000}]
    rk = daytrade.rank_from_flows(rows)
    assert [x["code"] for x in rk] == ["4526", "1101"]            # 淨賣超不列；摩根大通 4000 張不算
    assert rk[0]["net"] == 1400 and rk[0]["brokers"] == [["凱基-台北", 1600]] and rk[1]["net"] == 500 and rk[1]["pct"] == 0.5
    assert rk[0]["chg"] == 7.14

def test_tag_items_marks_short_list(monkeypatch):
    monkeypatch.setattr(daytrade.db, "get_meta", lambda k: {"date": "2026-10-27", "short": [{"code": "2330", "on_buy_pct": 3.2, "chg": 4.1}], "long": []} if k == "daytrade_close" else None)
    items = daytrade.tag_items([{"code": "2330"}, {"code": "2317"}])
    assert items[0]["dt"]["verdict"] == "short" and items[0]["dt"]["date"] == "2026-10-27" and "dt" not in items[1]

def test_judge_short_a_news_and_chg5_bonus():
    flows = [{"broker": "凱基-台北", "buy": 1200, "sell": 200, "net": 1000, "pct": 10.0}]
    base = _st(chg=6.0, close=106, open=101, high=106.5, low=100.5, vol_ratio=2.0, chg5=4.0)
    a = daytrade.judge(base, flows, ["凱基台北"], market_pct=0.8)
    b = daytrade.judge({**base, "news_n": 2, "news_title": "法人喊買"}, flows, ["凱基台北"], market_pct=0.8)
    c = daytrade.judge({**base, "chg5": 25.0}, flows, ["凱基台北"], market_pct=0.8)
    assert a["verdict"] == b["verdict"] == "short" and c["verdict"] == "watch"
    assert b["score"] > a["score"] and any("新聞" in r for r in b["reasons"]) and any("5 日已漲" in r for r in c["reasons"]) and any("執行條件" in r for r in a["risks"])

def test_judge_short_causal_rule():
    flows = []   # 不需要分點資料也能判斷
    ok = _st(chg=4.5, close=104.5, open=101, high=105, low=100.5, vol_ratio=2.0, chg5=6.0)
    assert daytrade.judge(ok, flows, ["凱基台北"], market_pct=0.8)["verdict"] == "short"
    assert daytrade.judge({**ok, "chg5": 15.0}, flows, ["凱基台北"], market_pct=0.8)["verdict"] == "watch"        # 5 日已漲 >=10 趨勢股
    assert daytrade.judge({**ok, "chg": 8.0, "close": 108}, flows, ["凱基台北"], market_pct=0.8)["verdict"] == "watch"   # 漲幅過大
    assert daytrade.judge(ok, flows, ["凱基台北"], market_pct=-0.5)["verdict"] == "watch"                      # 大盤收跌 = 逆勢
    j = daytrade.judge({**ok, "foreign": -800}, flows, ["凱基台北"], market_pct=0.8)
    assert j["score"] > daytrade.judge(ok, flows, ["凱基台北"], market_pct=0.8)["score"] and any("外資賣超" in r for r in j["reasons"]) and any("執行條件" in r for r in j["risks"])

def test_judge_short_a_requires_market_not_down():
    flows = [{"broker": "凱基-台北", "buy": 1200, "sell": 200, "net": 1000, "pct": 10.0}, {"broker": "元大-台北", "buy": 400, "sell": 100, "net": 300, "pct": 3.0}]
    st = _st(chg=6.0, close=106, open=101, high=106.5, low=100.5, vol_ratio=2.0)
    s2 = daytrade.judge(st, flows, ["凱基台北"], market_pct=0.8)
    assert s2["verdict"] == "short"
    j = daytrade.judge(st, flows, ["凱基台北"], market_pct=-1.5)   # 名單日大盤跌 → 逆勢強勢股，回測做空僅 44% → 觀察
    assert j["verdict"] == "watch" and any("逆勢" in r for r in j["reasons"])
    s3 = daytrade.judge(_st(chg=10.0, close=110.0, open=101, high=110.0, low=100.5, vol_ratio=2.0), flows, ["凱基台北"], market_pct=0.8)
    assert daytrade.judge(st, flows, ["凱基台北"], market_pct=None)["verdict"] == "watch"   # 大盤資料缺 → 不直接做空
    assert s3["verdict"] == "watch" and any("漲停" in r for r in s3["reasons"])   # 漲停股續強機率高 → 觀察

def test_outcome_and_long_rule_excludes_big_caps():
    o = daytrade.outcome({"verdict": "short", "close": 100.0}, {"open": 103.0, "high": 104.0, "low": 95.0, "close": 96.0})
    assert o["hit"] and o["gap"] == 3.0 and o["chg"] == -4.0 and round(o["move"], 2) == round((96 / 103 - 1) * 100, 2) and o["best"] == round((103 / 95 - 1) * 100, 2)
    o = daytrade.outcome({"verdict": "long", "close": 100.0}, {"open": 101.0, "high": 106.0, "low": 100.5, "close": 104.0})
    assert o["hit"] and o["best"] == round((106 / 101 - 1) * 100, 2)
    assert daytrade.outcome({"verdict": "long", "close": 100.0}, {}) is None
    # 隔日沖倒貨型做多: 大型股 (成交額 >= 30 億) 不算、量比不足不算
    flows = [{"broker": "凱基-台北", "buy": 50, "sell": 1000, "net": -950, "pct": 9.5}]
    base = dict(chg=1.2, close=104.5, high=105, low=100, vol_ratio=1.5, prev_chg=6.0)
    assert daytrade.judge(_st(**base), flows, ["凱基台北"])["verdict"] == "watch" and any("倒出" in r for r in daytrade.judge(_st(**base), flows, ["凱基台北"])["reasons"])
    nolong = lambda st: not any("倒出" in r for r in daytrade.judge(st, flows, ["凱基台北"])["reasons"])
    assert nolong(_st(**{**base, "prev_chg": 0.5}))   # 前一日沒大漲 → 隔日沖根本沒進場
    assert nolong(_st(**{**base, "amount": 5e9}))
    assert nolong(_st(**{**base, "vol_ratio": 0.8}))

def test_judge_watch_when_nothing_special():
    flows = [{"broker": "元大-台北", "buy": 100, "sell": 50, "net": 50, "pct": 0.5}]
    j = daytrade.judge(_st(chg=0.5, close=100.5, high=101, low=99), flows, ["凱基台北"])
    assert j["verdict"] == "watch" and j["reasons"] == []

def test_parse_msg_realtime_fields():
    m = {"c": "2330", "n": "台積電", "z": "-", "tv": "-", "v": "14195", "y": "2385.0000", "o": "2380.0000", "h": "2405.0000", "l": "2380.0000", "d": "20261027", "t": "10:06:00",
         "a": "2400.0000_2405.0000_2410.0000_2415.0000_2420.0000_", "b": "2395.0000_2390.0000_2385.0000_2380.0000_2375.0000_",
         "f": "629_766_757_347_428_", "g": "512_831_508_767_383_", "u": "2620.0000", "w": "2150.0000", "trade": {"t": "10:05:10", "v": 1, "z": "2400.0000"}}
    r = realtime.parse_msg(m, today="20261027")
    assert r["price"] == 2400.0 and r["live"] and r["volume"] == 14195 and r["tick_vol"] is None
    assert r["bid"] == 2395.0 and r["ask"] == 2400.0 and r["ask_vol"] == 629 + 766 + 757 + 347 + 428 and r["bid_vol"] == 512 + 831 + 508 + 767 + 383
    assert r["pct"] == round((2400 / 2385 - 1) * 100, 2) and r["limit_up"] == 2620.0 and r["trade_time"] == "10:05:10"
    m2 = {**m, "z": "2402.0000", "tv": "35", "d": "20261026"}
    r2 = realtime.parse_msg(m2, today="20261027")
    assert r2["price"] == 2402.0 and r2["tick_vol"] == 35 and not r2["live"]

def test_api_structure():
    os.environ["DAYTRADE_DISABLE"] = "1"
    from fastapi.testclient import TestClient
    from app import server
    with TestClient(server.app) as c:
        j = c.get("/api/daytrade/live?limit=5").json()
        assert set(["items", "total", "trading", "pool", "poll_sec"]) <= set(j) and j["poll_sec"] == 5 and len(j["items"]) <= 5 and j["min_lots"] == 10000
        for x in j["items"]: assert x["prev_lots"] >= 10000 or x["volume"] >= 10000
        j = c.get("/api/daytrade/close").json()
        assert "report" in j and "status" in j and "target_date" in j
        rep = j["report"]
        if rep:
            assert set(["date", "long", "short", "watch", "n_candidates"]) <= set(rep)
            for x in rep["short"]: assert x["verdict"] == "short" and (x["chg"] >= 3 or x["chg"] <= -3) and x["reasons"] and x["lots"] >= 10000
            for x in rep["long"]: assert x["verdict"] == "long" and x["reasons"]
        assert c.get("/api/daytrade/bars/0000").status_code == 404
        v = c.get("/api/daytrade/verify").json(); assert "days" in v and "summary" in v
        for day in v["days"]:
            for i in day["items"]: assert i["verdict"] in ("long", "short") and isinstance(i["hit"], bool)
        assert "close" in c.get("/api/daytrade/status").json()
