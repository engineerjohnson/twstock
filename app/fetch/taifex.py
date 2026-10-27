"""期交所 (TAIFEX) 臺指期資料：即時報價 (日盤 / 夜盤) 與歷史日資料 (含盤後交易時段)。

- 夜盤 15:00～隔日 05:00，反映美股；開盤前 (08:30) 就知道。
- 日盤 08:45 開盤，比現股早 15 分鐘：期貨開盤跳空是當沖執行閘門最早的訊號。
"""
import csv, io, datetime, requests

QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteList"
HIST_URL = "https://www.taifex.com.tw/cht/3/futDataDown"
_H = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Referer": "https://mis.taifex.com.tw/futures/"}


def _f(x):
    try: return float(str(x).replace(",", "")) if x not in (None, "", "-") else None
    except Exception: return None


def parse_quote_list(lst):
    """純函式：期交所 QuoteList → {"spot": {...}, "near": {...}}。near = 近月臺指期 (成交量最大的月契約)。"""
    spot, near = None, None
    for q in lst or []:
        sid = q.get("SymbolID") or ""
        rec = {"name": q.get("DispCName"), "symbol": sid, "last": _f(q.get("CLastPrice")), "ref": _f(q.get("CRefPrice")), "open": _f(q.get("COpenPrice")),
               "high": _f(q.get("CHighPrice")), "low": _f(q.get("CLowPrice")), "vol": _f(q.get("CTotalVolume")) or 0, "time": q.get("CTime"), "date": q.get("CDate")}
        if rec["ref"]:
            rec["pct"] = round((rec["last"] / rec["ref"] - 1) * 100, 2) if rec["last"] else None
            rec["open_pct"] = round((rec["open"] / rec["ref"] - 1) * 100, 2) if rec["open"] else None
        base = sid.split("-")[0]
        if base == "TXF": spot = rec                                                   # TXF-S 現貨
        elif base.startswith("TXF") and "W" not in base[3:]:                           # TXFK6-F 月契約 (週契約為 TXFK6W5)
            if near is None or rec["vol"] > near["vol"]: near = rec
    return {"spot": spot, "near": near}


def fetch_quote(market="0", timeout=20):
    """market: "0" 日盤、"1" 夜盤。回傳 parse_quote_list 結果；失敗回 None。"""
    body = {"MarketType": market, "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "", "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}
    try:
        r = requests.post(QUOTE_URL, json=body, headers=_H, timeout=timeout)
        j = r.json()
        return parse_quote_list((j.get("RtData") or {}).get("QuoteList") or [])
    except Exception as e:
        print("taifex quote", market, e); return None


def parse_history_csv(text):
    """純函式：futDataDown CSV → {date: {"day": {o,h,l,c,v,month}, "night": {...}}} (近月 = 成交量最大的月契約)。"""
    out = {}
    for x in csv.reader(io.StringIO(text)):
        if len(x) < 18 or x[1].strip() != "TX": continue
        month = x[2].strip()
        if "W" in month or "/" in month or not month: continue
        sess = "day" if x[17].strip() == "一般" else "night"
        o, h, l, c, v = _f(x[3]), _f(x[4]), _f(x[5]), _f(x[6]), _f(x[9]) or 0
        if not (o and h and l and c): continue
        rec = out.setdefault(x[0].replace("/", "-"), {})
        if rec.get(sess) is None or v > rec[sess]["v"]: rec[sess] = {"month": month, "o": o, "h": h, "l": l, "c": c, "v": v}
    return out


def fetch_history(start, end):
    """期交所歷史日資料 (一次最多 30 天，自動分段)。start/end: datetime.date。"""
    out = {}
    d0 = start
    while d0 <= end:
        d1 = min(d0 + datetime.timedelta(days=29), end)
        try:
            r = requests.post(HIST_URL, data={"down_type": "1", "commodity_id": "TX", "queryStartDate": d0.strftime("%Y/%m/%d"), "queryEndDate": d1.strftime("%Y/%m/%d")},
                              headers={"User-Agent": "Mozilla/5.0", "Referer": HIST_URL}, timeout=60)
            out.update(parse_history_csv(r.content.decode("big5", "ignore")))
        except Exception as e: print("taifex history", d0, e)
        d0 = d1 + datetime.timedelta(days=1)
    return out
