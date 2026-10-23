"""TPEx (上櫃) fetchers."""
from .common import get_json, num, is_stock_code, iso

def _d(d):
    return f"{d.year}/{d.month:02d}/{d.day:02d}"

def fetch_daily(d):
    j = get_json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={_d(d)}&id=&response=json")
    if str(j.get("stat", "")).lower() != "ok": return None
    if j.get("date") and j["date"] != d.strftime("%Y%m%d"): return None  # holiday -> TPEx returns other date
    tables = j.get("tables") or []
    if not tables or not tables[0].get("data"): return None
    rows, names = [], []
    for r in tables[0]["data"]:
        code = r[0].strip()
        if not is_stock_code(code): continue
        close = num(r[2])
        if close is None: continue
        rows.append((code, iso(d), num(r[4]), num(r[5]), num(r[6]), close, num(r[8]), num(r[9]), num(r[10])))
        names.append((code, r[1].strip(), "TPEx"))
    return rows, names

def fetch_insti(d):
    j = get_json(f"https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&date={_d(d)}&response=json")
    if str(j.get("stat", "")).lower() != "ok": return None
    if j.get("date") and j["date"] != d.strftime("%Y%m%d"): return None
    tables = j.get("tables") or []
    if not tables or not tables[0].get("data"): return None
    rows = []
    for r in tables[0]["data"]:
        code = r[0].strip()
        if not is_stock_code(code): continue
        fn = num(r[10]) or 0; tn = num(r[13]) or 0; dn = num(r[22]) or 0
        tot = num(r[23])
        rows.append((code, iso(d), fn, tn, dn, tot if tot is not None else (fn + tn + dn)))
    return rows

def fetch_valuation():
    j = get_json("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis", sleep=0)
    return {r["SecuritiesCompanyCode"]: (num(r.get("PriceEarningRatio")), num(r.get("PriceBookRatio")), num(r.get("YieldRatio")))
            for r in j if is_stock_code(r.get("SecuritiesCompanyCode", ""))}

def fetch_companies():
    j = get_json("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", sleep=0)
    return [(r["SecuritiesCompanyCode"], r["CompanyAbbreviation"].strip(), "TPEx", r.get("SecuritiesIndustryCode", ""))
            for r in j if is_stock_code(r.get("SecuritiesCompanyCode", ""))]
