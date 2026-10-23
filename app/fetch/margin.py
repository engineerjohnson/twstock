"""融資融券餘額 (TWSE MI_MARGN / TPEx margin balance)."""
from .common import get_json, num, is_stock_code, iso, ymd

def fetch_twse(d):
    j = get_json(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ymd(d)}&selectType=ALL&response=json")
    if j.get("stat") != "OK": return None
    rows = []
    for tb in j.get("tables", []):
        f = tb.get("fields") or []
        if len(f) >= 15 and f[0] == "代號":
            # 代號,名稱, 融資: 買進,賣出,現金償還,前日餘額,今日餘額,次一營業日限額 | 融券: 買進,賣出,現券償還,前日餘額,今日餘額,限額 | 資券互抵, 註記
            for r in tb["data"]:
                code = r[0].strip()
                if not is_stock_code(code): continue
                fin_prev, fin_now = num(r[5]) or 0, num(r[6]) or 0
                sh_prev, sh_now = num(r[11]) or 0, num(r[12]) or 0
                rows.append((code, iso(d), fin_now, fin_now - fin_prev, sh_now, sh_now - sh_prev))
    return rows

def fetch_tpex(d):
    j = get_json(f"https://www.tpex.org.tw/www/zh-tw/margin/balance?date={d.year}/{d.month:02d}/{d.day:02d}&response=json")
    if str(j.get("stat", "")).lower() != "ok": return None
    if j.get("date") and j["date"] != d.strftime("%Y%m%d"): return None
    tables = j.get("tables") or []
    if not tables or not tables[0].get("data"): return None
    rows = []
    for r in tables[0]["data"]:
        code = r[0].strip()
        if not is_stock_code(code): continue
        # 代號,名稱,前資餘額,資買,資賣,現償,資餘額,資屬證金,資使用率,資限額,前券餘額,券賣,券買,券償,券餘額,...
        fin_prev, fin_now = num(r[2]) or 0, num(r[6]) or 0
        sh_prev, sh_now = num(r[10]) or 0, num(r[14]) or 0
        rows.append((code, iso(d), fin_now, fin_now - fin_prev, sh_now, sh_now - sh_prev))
    return rows
