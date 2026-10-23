"""盤中即時報價 (證交所 MIS API, 約 5 秒延遲)."""
import time, datetime, requests
from ..config import HTTP_HEADERS
from .. import db

_cache = {}  # key -> (time, data)
_markets = {}

def _market(code):
    if not _markets:
        for r in db.query("SELECT code, market FROM stocks"): _markets[r["code"]] = r["market"]
    return "otc" if _markets.get(code) == "TPEx" else "tse"

def is_trading_time(now=None):
    """交易時段 (08:55-13:40 平日) 且當日確實有成交 (以台積電即時報價日期判斷，避免颱風假/假日誤判)."""
    now = now or datetime.datetime.now()
    if not (now.weekday() < 5 and datetime.time(8, 55) <= now.time() <= datetime.time(13, 40)): return False
    q = quotes(["2330"], ttl=60).get("2330")
    return bool(q and q.get("live"))

def quotes(codes, ttl=10):
    """Return {code: {price, change, pct, open, high, low, volume(張), time, bid, ask}} for up to ~150 codes."""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes: return {}
    key = ",".join(codes)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    out = {}
    s = requests.Session(); s.headers.update({**HTTP_HEADERS, "Referer": "https://mis.twse.com.tw/stock/index.jsp"})
    for i in range(0, len(codes), 50):
        batch = "|".join(f"{_market(c)}_{c}.tw" for c in codes[i:i + 50])
        try:
            j = s.get(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={batch}&json=1&delay=0", timeout=15).json()
        except Exception as e:
            print("realtime", e); continue
        for m in j.get("msgArray", []):
            def f(k):
                v = m.get(k)
                try: return float(v) if v not in (None, "", "-") else None
                except ValueError: return None
            price = f("z")
            if price is None and isinstance(m.get("b"), str) and m["b"]:  # 尚無成交時以最佳買價代替
                try: price = float(m["b"].split("_")[0])
                except ValueError: price = None
            prev = f("y")
            if price is None and prev is None: continue
            p = price if price is not None else prev
            today = datetime.date.today().strftime("%Y%m%d")
            out[m["c"]] = {"price": p, "prev": prev, "change": round(p - prev, 2) if prev else None,
                           "pct": round((p / prev - 1) * 100, 2) if prev else None, "open": f("o"), "high": f("h"), "low": f("l"),
                           "volume": f("v"), "time": m.get("t"), "date": m.get("d"), "name": m.get("n"), "live": price is not None and m.get("d") == today}
    if len(_cache) > 50: _cache.clear()
    _cache[key] = (time.time(), out)
    return out
