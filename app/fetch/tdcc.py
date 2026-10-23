"""集保戶股權分散表 (weekly) — 大戶持股 (千張大戶 / 400張以上)."""
import re, csv, io, time
import requests
from .common import get
from ..config import HTTP_HEADERS
from .. import db

def update_bulk():
    """Latest weekly snapshot for all stocks (TDCC open data)."""
    r = get("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5", timeout=180, sleep=0)
    txt = r.content.decode("utf-8-sig", errors="replace")
    rows, date = [], None
    for rec in csv.reader(io.StringIO(txt)):
        if len(rec) < 6 or not rec[0].isdigit(): continue
        d = rec[0]; code = rec[1].strip()
        if not re.fullmatch(r"[1-9]\d{3}", code): continue
        date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        try: rows.append((code, date, int(rec[2]), int(rec[3]), float(rec[4]), float(rec[5])))
        except ValueError: pass
    db.executemany("INSERT OR REPLACE INTO tdcc(code,date,level,holders,shares,pct) VALUES(?,?,?,?,?,?)", rows)
    if date: db.set_meta("tdcc_bulk_date", date)
    return date, len(rows)

def _form():
    s = requests.Session(); s.headers.update(HTTP_HEADERS)
    r = s.get("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", timeout=40)
    tok = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"', r.text).group(1)
    uri = re.search(r'name="SYNCHRONIZER_URI" value="([^"]+)"', r.text).group(1)
    dates = re.findall(r'<option value="(\d{8})"', r.text)
    return s, tok, uri, dates

def fetch_stocks_weeks(codes, weeks=2, progress=None):
    """Query the TDCC web form for the latest N weekly snapshots of given stocks; store into db.
    Skips weeks already in db. Returns list of ISO dates available."""
    s, tok, uri, dates = _form()
    want = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dates[:weeks]]
    for i, code in enumerate(codes):
        for d, iso in zip(dates[:weeks], want):
            if db.query("SELECT 1 FROM tdcc WHERE code=? AND date=? LIMIT 1", (code, iso)): continue
            try:
                r = s.post("https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", timeout=40,
                           data={"SYNCHRONIZER_TOKEN": tok, "SYNCHRONIZER_URI": uri, "method": "submit", "firDate": dates[0],
                                 "scaDate": d, "sqlMethod": "StockNo", "stockNo": code, "stockName": ""})
            except Exception as e:
                print("tdcc form", code, e); continue
            m = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"', r.text)  # token is single-use; refresh each time
            if m: tok = m.group(1)
            rows = []
            for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", r.text, re.S):
                cells = [re.sub(r"<[^>]+>", "", c).strip().replace(",", "") for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
                if len(cells) == 5 and cells[0].isdigit():
                    try: rows.append((code, iso, int(cells[0]), int(cells[2]), float(cells[3]), float(cells[4])))  # 序, 分級, 人數, 股數, 占比
                    except ValueError: pass
            if rows:
                db.executemany("INSERT OR REPLACE INTO tdcc(code,date,level,holders,shares,pct) VALUES(?,?,?,?,?,?)", rows)
            time.sleep(0.4)
        if progress: progress(i + 1, len(codes))
    return want
