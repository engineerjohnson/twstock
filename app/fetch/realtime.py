"""盤中即時報價 (證交所 MIS API, 約 5 秒延遲)."""
import time, datetime, requests
from concurrent.futures import ThreadPoolExecutor
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

def _f(v):
    try: return float(v) if v not in (None, "", "-") else None
    except (TypeError, ValueError): return None

def _levels(s):
    """'2400.0000_2405.0000_' -> [2400.0, 2405.0]"""
    if not isinstance(s, str): return []
    out = []
    for x in s.split("_"):
        v = _f(x)
        if v is not None and v > 0: out.append(v)   # 漲停無賣單 / 跌停無買單時 MIS 會回 0
    return out

def parse_msg(m, today=None):
    """把 MIS 一筆 msgArray 轉成報價 dict (純函式，方便測試)。
    欄位: z 最新成交價 (該 5 秒快照內無成交時為 '-')、trade.z 最後一筆成交價、tv 本盤成交量(張)、v 累計成交量(張)、
    a/f 五檔賣價/量、b/g 五檔買價/量、o/h/l 開高低、y 昨收、t 快照時間。"""
    today = today or datetime.date.today().strftime("%Y%m%d")
    price = _f(m.get("z"))
    trade = m.get("trade") if isinstance(m.get("trade"), dict) else {}
    last_trade = _f(trade.get("z"))
    tick_vol = _f(m.get("tv"))             # 本盤 (最近一筆快照內) 成交量, 無成交為 None
    if price is None:
        price = last_trade
        tick_vol = None
    asks, bids = _levels(m.get("a")), _levels(m.get("b"))
    ask_vols, bid_vols = _levels(m.get("f")), _levels(m.get("g"))
    prev = _f(m.get("y"))
    if price is None and bids: price = bids[0]  # 尚無成交時以最佳買價代替
    if price is None and prev is None: return None
    p = price if price is not None else prev
    return {"price": p, "prev": prev, "change": round(p - prev, 2) if prev else None,
            "pct": round((p / prev - 1) * 100, 2) if prev else None, "open": _f(m.get("o")), "high": _f(m.get("h")), "low": _f(m.get("l")),
            "volume": _f(m.get("v")), "tick_vol": tick_vol, "time": m.get("t"), "trade_time": trade.get("t") or m.get("t"), "date": m.get("d"),
            "name": m.get("n"), "live": (price is not None or last_trade is not None) and m.get("d") == today,
            "ask": asks[0] if asks else None, "bid": bids[0] if bids else None,
            "ask_vol": sum(ask_vols) if ask_vols else None, "bid_vol": sum(bid_vols) if bid_vols else None,
            "asks": asks, "bids": bids, "ask_vols": ask_vols, "bid_vols": bid_vols,
            "limit_up": _f(m.get("u")), "limit_down": _f(m.get("w"))}

def _fetch_batch(session, codes):
    batch = "|".join(f"{_market(c)}_{c}.tw" for c in codes)
    try:
        j = session.get(f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={batch}&json=1&delay=0", timeout=15).json()
    except Exception as e:
        print("realtime", e); return {}
    today = datetime.date.today().strftime("%Y%m%d")
    out = {}
    for m in j.get("msgArray", []):
        q = parse_msg(m, today)
        if q: out[m["c"]] = q
    return out

def quotes(codes, ttl=10, workers=1):
    """Return {code: {price, change, pct, open, high, low, volume(張), tick_vol, bid, ask, bid_vol, ask_vol, ...}} 每 50 檔一次請求。"""
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes: return {}
    key = ",".join(codes)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    s = requests.Session(); s.headers.update({**HTTP_HEADERS, "Referer": "https://mis.twse.com.tw/stock/index.jsp"})
    batches = [codes[i:i + 50] for i in range(0, len(codes), 50)]
    out = {}
    if workers > 1 and len(batches) > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(lambda b: _fetch_batch(s, b), batches): out.update(r)
    else:
        for b in batches: out.update(_fetch_batch(s, b))
    if len(_cache) > 50: _cache.clear()
    _cache[key] = (time.time(), out)
    return out
