"""公司基本資料 / 月營收 / 季EPS / 本益比 from TWSE & TPEx open data (MOPS mirrors)."""
import datetime
from .common import get_json, num, is_stock_code
from . import twse, tpex
from .. import db

INDUSTRY = {"01":"水泥","02":"食品","03":"塑膠","04":"紡織","05":"電機機械","06":"電器電纜","08":"玻璃陶瓷","09":"造紙","10":"鋼鐵",
 "11":"橡膠","12":"汽車","14":"建材營造","15":"航運","16":"觀光餐旅","17":"金融保險","18":"貿易百貨","19":"綜合","20":"其他",
 "21":"化學","22":"生技醫療","23":"油電燃氣","24":"半導體","25":"電腦週邊","26":"光電","27":"通信網路","28":"電子零組件",
 "29":"電子通路","30":"資訊服務","31":"其他電子","32":"文化創意","33":"農業科技","34":"電子商務","35":"綠能環保","36":"數位雲端",
 "37":"運動休閒","38":"居家生活","80":"管理股票","91":"存託憑證","40":"ETF","41":"創新板"}

def update_companies():
    comps = []
    for fn in (twse.fetch_companies, tpex.fetch_companies):
        try: comps += fn()
        except Exception as e: print("companies", fn.__module__, e)
    db.executemany("INSERT OR REPLACE INTO stocks(code,name,market,industry) VALUES(?,?,?,?)",
                   [(c, n, m, INDUSTRY.get(str(i).strip(), str(i).strip())) for c, n, m, i in comps])
    return len(comps)

def update_all():
    update_companies()
    rev = {}
    for url in ("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O"):
        try:
            for r in get_json(url, sleep=0):
                code = r.get("公司代號", "").strip()
                if not is_stock_code(code): continue
                rev[code] = (r.get("資料年月"), num(r.get("營業收入-當月營收")), num(r.get("營業收入-上月比較增減(%)")),
                             num(r.get("營業收入-去年同月增減(%)")), num(r.get("累計營業收入-前期比較增減(%)")))
        except Exception as e: print("revenue", url, e)
    eps = {}
    try:
        for r in get_json("https://openapi.twse.com.tw/v1/opendata/t187ap14_L", sleep=0):
            code = r.get("公司代號", "").strip()
            if is_stock_code(code): eps[code] = (num(r.get("基本每股盈餘(元)")), r.get("年度"), r.get("季別"), num(r.get("稅後淨利")))
    except Exception as e: print("eps L", e)
    try:
        for r in get_json("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O", sleep=0):
            code = r.get("SecuritiesCompanyCode", "").strip()
            if is_stock_code(code): eps[code] = (num(r.get("基本每股盈餘")), r.get("Year"), r.get("季別"), num(r.get("稅後淨利")))
    except Exception as e: print("eps O", e)
    val = {}
    for fn in (twse.fetch_valuation, tpex.fetch_valuation):
        try: val.update(fn())
        except Exception as e: print("valuation", fn.__module__, e)
    codes = set(rev) | set(eps) | set(val)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for c in codes:
        rv = rev.get(c, (None,) * 5); ep = eps.get(c, (None,) * 4); v = val.get(c, (None,) * 3)
        rows.append((c, rv[0], rv[1], rv[2], rv[3], rv[4], ep[0], ep[1], ep[2], ep[3], v[0], v[1], v[2], now))
    db.executemany("""INSERT OR REPLACE INTO fundamentals(code,rev_month,rev,rev_mom,rev_yoy,rev_cum_yoy,eps_q,eps_year,eps_season,
        net_income,pe,pb,yield,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    db.set_meta("fundamentals_updated", now)
    return len(rows)
