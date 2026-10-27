"""券商分點進出 (富邦 e01 DJ 頁面, Big5) 與 證交所/櫃買「當日沖銷交易統計」。"""
import re, time, datetime, requests
from ..config import HTTP_HEADERS
from .common import num, roc_to_iso

BROKER_URL = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco.djhtm?a={code}&e={d}&f={d}"
_session = requests.Session(); _session.headers.update(HTTP_HEADERS)

def _cells(row):
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<TD[^>]*>(.*?)</TD>", row, re.S | re.I)]

def parse_broker_html(html):
    """解析分點進出頁面 -> {"date": '2026-10-22', "buy": [{broker, buy, sell, net, pct}], "sell": [...], "buy_total", "sell_total"}
    買超/賣超各列最多 15 家 (張)。純函式，方便測試。"""
    m = re.search(r"最後更新[^0-9]{0,10}(\d{4})/(\d{2})/(\d{2})", html) or re.search(r"(\d{4})/(\d{2})/(\d{2})", html)
    date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None
    buy, sell = [], []
    buy_total = sell_total = None
    for row in re.findall(r"<TR[^>]*>(.*?)</TR>", html, re.S | re.I):
        c = _cells(row)
        if len(c) == 10 and (num(c[3]) is not None or num(c[8]) is not None):
            if c[0] and num(c[3]) is not None: buy.append({"broker": c[0], "buy": num(c[1]), "sell": num(c[2]), "net": num(c[3]), "pct": num(c[4].rstrip("%"))})
            if c[5] and num(c[8]) is not None: sell.append({"broker": c[5], "buy": num(c[6]), "sell": num(c[7]), "net": -(num(c[8]) or 0), "pct": num(c[9].rstrip("%"))})
        elif len(c) == 4 and "合計買超" in c[0]:
            buy_total, sell_total = num(c[1]), num(c[3])
    return {"date": date, "buy": buy, "sell": sell, "buy_total": buy_total, "sell_total": sell_total}

def fetch_broker(code, date, sleep=0.25):
    """抓一檔某日的分點進出 (date: 'YYYY-MM-DD'); 回傳 parse_broker_html 結果 (date 為頁面標示的最後更新日)。"""
    url = BROKER_URL.format(code=code, d=date)
    last = None
    for i in range(3):
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 200:
                if sleep: time.sleep(sleep)
                return parse_broker_html(r.content.decode("cp950", "ignore"))
            last = Exception(f"HTTP {r.status_code}")
        except Exception as e: last = e
        time.sleep(1 + i)
    raise last

def broker_data_date():
    """富邦分點資料目前更新到哪一天 (以台積電頁面判斷)。"""
    try: return fetch_broker("2330", datetime.date.today().isoformat(), sleep=0).get("date")
    except Exception: return None

def normalize_broker(name):
    return re.sub(r"[\s\-－‐_()（）]|證券|金鼎|股份有限公司", "", name or "")

def is_overnight(name, patterns):
    """是否為隔日沖券商分點。patterns 為 config.OVERNIGHT_BROKERS；'凱基台北' 可比對 '凱基-台北'、'群益金鼎大安' 可比對 '群益金鼎-大安'。
    採「去掉符號後完全相同」比對，避免 '統一' (總公司) 誤判成 '統一台北'、'元大證券' 誤判成 '元大土城永寧'。"""
    n = normalize_broker(name)
    if not n: return False
    return any(normalize_broker(p) == n for p in patterns)

# ---------- 當日沖銷交易統計 (證交所 / 櫃買) ----------
def _rows(fields, data, date):
    out = []
    for r in data:
        if len(r) < 6: continue
        code = str(r[0]).strip()
        if not re.fullmatch(r"\d{4}", code): continue
        out.append((code, date, num(r[3]) or 0, num(r[4]) or 0, num(r[5]) or 0, str(r[2]).strip()))
    return out

def fetch_daytrade_stat(d):
    """回傳 ([(code,date,dt_shares,dt_buy,dt_sell,flag)], market_summary) ; d: datetime.date。無資料回傳 ([], None)。"""
    date = d.isoformat(); rows = []; summary = {}
    try:
        j = _session.get(f"https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date={d.strftime('%Y%m%d')}&selectType=All", timeout=40).json()
        for t in j.get("tables", []):
            data = t.get("data") or []
            if data and len(data[0]) == 6 and re.fullmatch(r"\d{4}[A-Z]?|\d{5,6}[A-Z]?", str(data[0][0]).strip()): rows += _rows(t.get("fields"), data, date)
            elif data and len(data[0]) == 6 and str(data[0][1]).replace(".", "").isdigit():
                summary["twse"] = {"shares": num(data[0][0]), "share_pct": num(data[0][1]), "buy": num(data[0][2]), "sell": num(data[0][4])}
    except Exception as e: print("TWTB4U", e)
    time.sleep(0.5)
    try:
        j = _session.get(f"https://www.tpex.org.tw/www/zh-tw/intraday/stat?date={d.strftime('%Y/%m/%d')}&type=Daily&response=json", timeout=40).json()
        for t in j.get("tables", []):
            data = t.get("data") or []
            if data and len(data[0]) == 6 and re.fullmatch(r"\d{4,6}[A-Z]?", str(data[0][0]).strip()): rows += _rows(t.get("fields"), data, date)
            elif data and len(data[0]) == 6 and "%" in str(data[0][1]):
                summary["tpex"] = {"shares": num(data[0][0]), "share_pct": num(str(data[0][1]).rstrip("%")), "buy": num(data[0][2]), "sell": num(data[0][4])}
    except Exception as e: print("TPEx 當沖", e)
    return rows, (summary or None)
