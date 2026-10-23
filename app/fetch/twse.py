"""TWSE (上市) fetchers."""
from .common import get_json, num, is_stock_code, iso, ymd

def fetch_daily(d):
    """All listed stocks' daily quotes for date d. Returns (rows, names) or None if not a trading day."""
    j = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd(d)}&type=ALLBUT0999&response=json")
    if j.get("stat") != "OK": return None
    rows, names = [], []
    for tb in j.get("tables", []):
        f = tb.get("fields") or []
        if len(f) >= 16 and f[0] == "證券代號":
            for r in tb["data"]:
                code = r[0].strip()
                if not is_stock_code(code): continue
                close = num(r[8])
                if close is None: continue
                rows.append((code, iso(d), num(r[5]), num(r[6]), num(r[7]), close, num(r[2]), num(r[4]), num(r[3])))
                names.append((code, r[1].strip(), "TWSE"))
    return rows, names

def fetch_insti(d):
    """三大法人買賣超 per stock (shares)."""
    j = get_json(f"https://www.twse.com.tw/rwd/zh/fund/T86?date={ymd(d)}&selectType=ALLBUT0999&response=json")
    if j.get("stat") != "OK": return None
    rows = []
    for r in j.get("data", []):
        code = r[0].strip()
        if not is_stock_code(code): continue
        fn = (num(r[4]) or 0) + (num(r[7]) or 0)
        tn = num(r[10]) or 0
        dn = num(r[11]) or 0
        rows.append((code, iso(d), fn, tn, dn, num(r[18]) if num(r[18]) is not None else (fn + tn + dn)))
    return rows

def fetch_insti_total(d):
    """三大法人買賣金額統計 (市場合計, 元)."""
    j = get_json(f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&dayDate={ymd(d)}&response=json")
    if j.get("stat") != "OK": return None
    out = {}
    for r in j.get("data", []):
        out[r[0].strip()] = num(r[3])
    return out

def fetch_index_summary(d):
    """大盤指數 (加權/電子/金融/半導體) 收盤與漲跌."""
    j = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd(d)}&type=IND&response=json")
    if j.get("stat") != "OK": return None
    out = {}
    want = ("發行量加權股價指數", "電子類指數", "金融保險類指數", "半導體類指數", "臺灣50指數")
    for tb in j.get("tables", []):
        for r in tb.get("data", []):
            if r and r[0].strip() in want and r[0].strip() not in out:
                sign = -1 if ("green" in str(r[2]) or "-" in str(r[2]).replace("<p", "")) else 1
                out[r[0].strip()] = {"close": num(r[1]), "change": sign * abs(num(r[3]) or 0), "pct": sign * abs(num(r[4]) or 0)}
    return out

def fetch_market_turnover(d):
    """FMTQIK: 成交金額 / 加權指數 for the month containing d."""
    j = get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ymd(d)}&response=json")
    if j.get("stat") != "OK": return None
    return j.get("data", [])

def fetch_valuation():
    """本益比/殖利率/股價淨值比 (latest)."""
    j = get_json("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", sleep=0)
    return {r["Code"]: (num(r.get("PEratio")), num(r.get("PBratio")), num(r.get("DividendYield"))) for r in j if is_stock_code(r.get("Code", ""))}

def fetch_companies():
    j = get_json("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", sleep=0)
    return [(r["公司代號"], r["公司簡稱"].strip(), "TWSE", r.get("產業別", "")) for r in j if is_stock_code(r.get("公司代號", ""))]
