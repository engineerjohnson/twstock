"""當沖雷達.
盤中: 每 5 秒輪詢證交所 MIS，對掃描池 (前一交易日成交金額前 N 檔 + 自選股 + 高當沖比) 累計每個區間的成交量，
      以「成交價 vs 前一快照的最佳買/賣價」判斷內盤 (賣方主動) / 外盤 (買方主動)，彙整成 1 分 K、VWAP、時間量比、五檔掛單差。
收盤後: 以富邦分點進出頁抓候選股的券商買賣超，用「隔日沖券商」名單判斷隔日偏空 (隔日沖進場 → 隔天開高出貨)
      與偏多 (隔日沖倒貨完畢仍守住 / 主力非隔日沖的強勢股) 候選。
"""
import threading, time, datetime, json, traceback, pickle, os
from collections import deque
from . import db
from .config import DATA_DIR
STATE_FILE = os.path.join(DATA_DIR, "daytrade_state.pkl")   # 盤中狀態每分鐘存檔，重啟伺服器後同一天可接續累計內外盤
from .config import (DAYTRADE_POLL_SEC, DAYTRADE_POOL_SIZE, DAYTRADE_POOL_MIN_LOTS, DAYTRADE_MIN_LOTS, DAYTRADE_TOP, DAYTRADE_CLOSE_CANDIDATES, OVERNIGHT_BROKERS)
from .fetch import realtime, broker, taifex
from .fetch.common import is_stock_code

SESSION_OPEN, SESSION_CLOSE = datetime.time(9, 0), datetime.time(13, 30)
SESSION_MIN = 270

state = {"trading": False, "date": None, "last_poll": None, "polls": 0, "pool": 0, "error": None, "started": None,
         "close": {"running": False, "step": "", "progress": 0, "total": 0, "error": None, "date": None, "built": None}}
_lock = threading.RLock()
_stocks = {}        # code -> live state
_pool_date = None
_thread = None
_price_sync_date = None

# ---------------------------------------------------------------- 盤中: 內外盤分類 (純函式)
def _secs(t):
    """'11:03:57' -> 秒數 (無法解析回 None)。"""
    try:
        h, m, s = (t or "").split(":"); return int(h) * 3600 + int(m) * 60 + int(s)
    except (ValueError, AttributeError): return None

MAX_BOOK_AGE = 20   # 前一快照超過這個秒數就不拿它的買賣價比對 (太舊), 只用價格方向判斷

def classify(price, dv, last, stale=False):
    """回傳 (outer, inner): 將 dv 張成交量歸類為外盤 (買方主動, 成交在賣價) 或內盤 (賣方主動, 成交在買價)。
    last: 前一快照 {price, bid, ask}；價格介於買賣價之間時以價格方向判斷，無法判斷則平分。
    stale=True 表示前一快照太舊 (買賣價已不可信)，只用價格方向判斷。"""
    if dv <= 0: return 0.0, 0.0
    ask, bid, lp = (last or {}).get("ask"), (last or {}).get("bid"), (last or {}).get("price")
    if not stale:
        if ask and price >= ask: return dv, 0.0
        if bid and price <= bid: return 0.0, dv
    if lp is not None:
        if price > lp: return dv, 0.0
        if price < lp: return 0.0, dv
    return dv / 2, dv / 2

def _new_state(info):
    return {"code": info["code"], "name": info.get("name") or info["code"], "market": info.get("market") or "", "industry": info.get("industry") or "",
            "prev_lots": info.get("lots") or 0, "avg20_lots": info.get("avg20_lots") or info.get("lots") or 0, "prev_amount": info.get("amount") or 0,
            "price": None, "prev": None, "open": None, "high": None, "low": None, "volume": 0, "pct": None, "time": None,
            "outer": 0.0, "inner": 0.0, "unclassified": 0.0, "vwap_num": 0.0, "vwap_den": 0.0,
            "bid": None, "ask": None, "bid_vol": None, "ask_vol": None, "limit_up": None, "limit_down": None,
            "bars": deque(maxlen=300), "last": None, "yday": None}

def update_state(s, q):
    """用一筆即時報價更新個股狀態 (純函式，方便測試)。"""
    v = q.get("volume") or 0
    price = q.get("price")
    if price is None: return
    last = s["last"]
    t = q.get("time") or ""
    dv, o, i = 0.0, 0.0, 0.0
    if last is None:
        s["unclassified"] = v           # 啟動前已成交的量無法判斷內外盤
    else:
        # 證交所 MIS 有多台節點、資料新舊不一：比上一筆更舊的快照 (時間倒退或累積量變少) 一律忽略，避免重複計算與倒帶
        if t < (last.get("time") or "") or v < last["v"]: return
        dv = max(0.0, v - last["v"])
        gap = (_secs(t) or 0) - (_secs(last.get("time")) or 0)
        o, i = classify(price, dv, last, stale=gap > MAX_BOOK_AGE)
        s["outer"] += o; s["inner"] += i
    if dv > 0:
        s["vwap_num"] += dv * price; s["vwap_den"] += dv
    key = (q.get("time") or "")[:5]
    bars = s["bars"]
    if not bars or bars[-1]["t"] != key:
        bars.append({"t": key, "o": price, "h": price, "l": price, "c": price, "v": 0.0, "outer": 0.0, "inner": 0.0})
    b = bars[-1]
    b["h"] = max(b["h"], price); b["l"] = min(b["l"], price); b["c"] = price
    b["v"] += dv; b["outer"] += o; b["inner"] += i
    s.update(price=price, prev=q.get("prev") or s["prev"], open=q.get("open") if q.get("open") is not None else s["open"],
             high=q.get("high") if q.get("high") is not None else s["high"], low=q.get("low") if q.get("low") is not None else s["low"],
             volume=v, pct=q.get("pct"), time=q.get("time"), bid=q.get("bid"), ask=q.get("ask"), bid_vol=q.get("bid_vol"), ask_vol=q.get("ask_vol"),
             limit_up=q.get("limit_up") or s["limit_up"], limit_down=q.get("limit_down") or s["limit_down"])
    s["last"] = {"v": v, "price": price, "bid": q.get("bid"), "ask": q.get("ask"), "time": t}

def session_fraction(now=None):
    """09:00~13:30 已經過的比例 (0.004~1)。"""
    now = now or datetime.datetime.now()
    t = now.time()
    if t <= SESSION_OPEN: return 1 / SESSION_MIN
    if t >= SESSION_CLOSE: return 1.0
    mins = (now - now.replace(hour=9, minute=0, second=0, microsecond=0)).total_seconds() / 60
    return max(1 / SESSION_MIN, min(1.0, mins / SESSION_MIN))

def metrics(s, frac=None):
    """由個股狀態計算雷達指標 (純函式)。"""
    frac = frac or session_fraction()
    prev, price = s["prev"], s["price"]
    if not prev or price is None: return None
    hi, lo, op = s["high"] or price, s["low"] or price, s["open"] or price
    amp = (hi - lo) / prev * 100
    gap = (op / prev - 1) * 100
    vol = s["volume"] or 0
    expected = (s["avg20_lots"] or s["prev_lots"] or 0) * frac
    vol_ratio = vol / expected if expected > 0 else None
    classified = s["outer"] + s["inner"]
    outer_ratio = s["outer"] / classified * 100 if classified > 0 else None
    bars = list(s["bars"])
    net5 = sum(b["outer"] - b["inner"] for b in bars[-5:]) if bars else 0
    vol1 = bars[-1]["v"] if bars else 0
    n_bars = max(1, len(bars) - 1)
    avg_bar = classified / n_bars if n_bars and classified else 0
    burst = vol1 / avg_bar if avg_bar > 0 else None
    vwap = s["vwap_num"] / s["vwap_den"] if s["vwap_den"] > 0 else None
    vwap_pos = (price / vwap - 1) * 100 if vwap else None
    bv, av = s["bid_vol"] or 0, s["ask_vol"] or 0
    book = (bv - av) / (bv + av) * 100 if (bv + av) > 0 else None
    rng = hi - lo
    pos = (price - lo) / rng if rng > 0 else 0.5
    pct = s["pct"] if s["pct"] is not None else (price / prev - 1) * 100
    limit_up = s["limit_up"] and price >= s["limit_up"]
    limit_down = s["limit_down"] and price <= s["limit_down"]
    # 方向判斷 (多/空各四個條件)
    orr = outer_ratio if outer_ratio is not None else 50
    bull = sum([pct > 0, orr >= 55, (vwap_pos or 0) > 0, pos >= 0.6])
    bear = sum([pct < 0, orr <= 45, (vwap_pos or 0) < 0, pos <= 0.4])
    direction = "bull" if bull >= 3 and bull > bear else "bear" if bear >= 3 and bear > bull else "flat"
    mom10 = (price / bars[-10]["c"] - 1) * 100 if len(bars) >= 10 and bars[-10]["c"] else None   # 近 10 分鐘動能 (方向是落後指標，用它看有沒有轉向)
    sig = []
    if limit_up: sig.append("漲停")
    if limit_down: sig.append("跌停")
    if vol_ratio is not None and vol_ratio >= 2: sig.append(f"爆量{vol_ratio:.1f}x")
    if burst is not None and burst >= 3 and vol1 >= 50: sig.append(f"1分爆量{burst:.0f}x")
    if outer_ratio is not None and classified >= 300 and len(bars) >= 3:
        if outer_ratio >= 62: sig.append(f"外盤強{outer_ratio:.0f}%")
        elif outer_ratio <= 38: sig.append(f"內盤強{100 - outer_ratio:.0f}%")
    if vwap_pos is not None and abs(vwap_pos) >= 0.3: sig.append("站上均價" if vwap_pos > 0 else "跌破均價")
    if gap >= 2 and pct > gap: sig.append("開高走高")
    elif gap >= 2 and pct < gap - 1: sig.append("開高走低")
    elif gap <= -2 and pct < gap: sig.append("開低走低")
    elif gap <= -2 and pct > gap + 1: sig.append("開低走高")
    if pos >= 0.9 and amp >= 2: sig.append("近高點")
    elif pos <= 0.1 and amp >= 2: sig.append("近低點")
    y = s.get("yday") or {}
    if y.get("verdict") == "short":
        sig.append(f"昨空單:開高{gap:+.1f}%✔執行區" if 0 < gap <= 3 else "昨空單:開高>3%✘放棄" if gap > 3 else "昨空單:未開高✘放棄")
    if y.get("verdict") == "short" and classified >= 300:
        if direction == "bear" or ((vwap_pos or 0) < 0 and pct < gap): sig.append("昨空單:出貨中✔")
        elif direction == "bull" and pct > gap: sig.append("昨空單:續拉⚠")
    elif y.get("verdict") == "long" and classified >= 300:
        if direction == "bull" or ((vwap_pos or 0) > 0 and pct > gap): sig.append("昨多單:續攻✔")
        elif direction == "bear": sig.append("昨多單:轉弱⚠")
    if book is not None and (bv + av) >= 100 and not limit_up and not limit_down:
        if book >= 40: sig.append("買盤掛單厚")
        elif book <= -40: sig.append("賣壓掛單重")
    heat = (min(amp, 12) * 4 + min(vol_ratio or 0, 5) * 8 + min(abs(pct), 10) * 2 + min(burst or 0, 6) * 3
            + (abs(outer_ratio - 50) * 0.5 if outer_ratio is not None and classified >= 300 else 0) + min(vol / 10000, 6) * 6)
    if vol < 200: heat *= 0.3
    return {"amp": round(amp, 2), "gap": round(gap, 2), "pct": round(pct, 2), "vol_ratio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "est_day_lots": round(vol / frac) if frac else None, "outer": round(s["outer"]), "inner": round(s["inner"]), "unclassified": round(s["unclassified"]),
            "outer_ratio": round(outer_ratio, 1) if outer_ratio is not None else None, "net5": round(net5), "vol1": round(vol1),
            "burst": round(burst, 1) if burst is not None else None, "vwap": round(vwap, 2) if vwap else None,
            "vwap_pos": round(vwap_pos, 2) if vwap_pos is not None else None, "book": round(book) if book is not None else None,
            "pos": round(pos, 2), "direction": direction, "bull": bull, "bear": bear, "mom10": round(mom10, 2) if mom10 is not None else None, "signals": sig, "heat": round(heat, 1),
            "limit_up": bool(limit_up), "limit_down": bool(limit_down)}

# ---------------------------------------------------------------- 盤中: 掃描池與輪詢
def _engine():
    from .analysis import engine
    return engine

def build_pool():
    """掃描池: 前一交易日成交張數 >= 門檻、依成交金額排序前 N 檔 + 自選股 + 高當沖比 + 昨日隔日沖候選。"""
    d = _engine().get()
    rows = [s for s in d["stocks"].values() if is_stock_code(s["code"]) and (s.get("lots") or 0) >= DAYTRADE_POOL_MIN_LOTS]
    rows.sort(key=lambda s: -(s.get("amount") or 0))
    infos = {s["code"]: s for s in rows[:DAYTRADE_POOL_SIZE]}
    extra = [r["code"] for r in db.query("SELECT code FROM watchlist")]
    date = d.get("date")
    if date:
        extra += [r["code"] for r in db.query("SELECT s.code FROM daytrade_stat s JOIN daily d ON d.code=s.code AND d.date=s.date WHERE s.date=? AND d.volume>=? "
                                              "ORDER BY s.dt_shares/d.volume DESC LIMIT 40", (date, DAYTRADE_MIN_LOTS * 1000))]
    close = db.get_meta("daytrade_close") or {}
    extra += [x["code"] for x in (close.get("long") or []) + (close.get("short") or [])]
    for c in extra:
        if c in infos or not is_stock_code(c): continue
        s = d["stocks"].get(c)
        if s: infos[c] = s
        else:
            st = db.query("SELECT code,name,market,industry FROM stocks WHERE code=?", (c,))
            if st: infos[c] = {**st[0], "lots": 0, "avg20_lots": 0, "amount": 0}
    yday = {x["code"]: x for x in (close.get("long") or []) + (close.get("short") or [])} if close.get("date") and close["date"] < datetime.date.today().isoformat() else {}
    saved = load_state()
    with _lock:
        _stocks.clear()
        for c, info in infos.items():
            st = saved.get(c) or _new_state(info)
            y = yday.get(c)
            if y: st["yday"] = {"verdict": y["verdict"], "on_buy": y["on_buy"], "on_buy_pct": y["on_buy_pct"], "on_sell": y["on_sell"], "date": close["date"]}
            _stocks[c] = st
    state["pool"] = len(_stocks)
    if saved: print(f"daytrade: 接續今日已累計的盤中狀態 ({len(saved)} 檔)")
    return list(_stocks)

def save_state():
    try:
        with _lock: data = {"date": datetime.date.today().isoformat(), "stocks": dict(_stocks)}
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "wb") as f: pickle.dump(data, f)
        os.replace(tmp, STATE_FILE)
    except Exception as e: print("daytrade save_state", e)

def load_state():
    """讀回今日存檔的盤中狀態 (不是今天的就忽略)。"""
    try:
        if not os.path.exists(STATE_FILE): return {}
        with open(STATE_FILE, "rb") as f: data = pickle.load(f)
        return data["stocks"] if data.get("date") == datetime.date.today().isoformat() else {}
    except Exception as e:
        print("daytrade load_state", e); return {}

def futures_pct(date):
    """名單日的期貨資料 (meta tx_futures:{date}) → {"day_c", "night_pct" (夜盤收盤相對日盤收盤), "open_pct" (日盤開盤相對前一日日盤收盤)}。"""
    f = db.get_meta(f"tx_futures:{date}") or {}
    day, night = f.get("day") or {}, f.get("night") or {}
    out = {"day_c": day.get("c"), "day_pct": None, "night_pct": None, "open_pct": None}
    prev = db.query("SELECT key FROM meta WHERE key LIKE 'tx_futures:%' AND key < ? ORDER BY key DESC LIMIT 1", (f"tx_futures:{date}",))
    pd = (db.get_meta(prev[0]["key"]) or {}).get("day") if prev else None
    if day.get("c") and night.get("c"): out["night_pct"] = round((night["c"] / day["c"] - 1) * 100, 2)
    if pd and pd.get("c") and day.get("o"): out["open_pct"] = round((day["o"] / pd["c"] - 1) * 100, 2)
    if pd and pd.get("c") and day.get("c"): out["day_pct"] = round((day["c"] / pd["c"] - 1) * 100, 2)
    return out

def poll_futures():
    """抓臺指期即時：日盤近月 (08:45 起) 與夜盤 (前一晚 15:00～05:00)。存到 state["futures"]。"""
    try:
        day = taifex.fetch_quote("0"); night = taifex.fetch_quote("1")
        nd = (day or {}).get("near") or {}; nn = (night or {}).get("near") or {}
        cur = state.get("futures") or {}
        # 夜盤：開盤前 (<08:45) 顯示前一晚收盤；日盤開始後夜盤 API 會變成當晚 (尚未開始 = 空值)，保留早上抓到的值
        if nn.get("last"): cur["night"] = {"last": nn["last"], "ref": nn["ref"], "pct": nn.get("pct"), "time": nn.get("time"), "date": nn.get("date")}
        if nd.get("last"): cur["day"] = {"last": nd["last"], "ref": nd["ref"], "open": nd["open"], "pct": nd.get("pct"), "open_pct": nd.get("open_pct"), "high": nd["high"], "low": nd["low"], "time": nd.get("time"), "date": nd.get("date"), "symbol": nd.get("symbol")}
        cur["updated"] = datetime.datetime.now().strftime("%H:%M:%S")
        state["futures"] = cur
    except Exception as e: print("poll_futures", e)

def sync_futures_history(days=10):
    """把期交所歷史日資料 (日盤 + 夜盤) 存進 meta tx_futures:{date}，供驗證與名單使用。"""
    end = datetime.date.today(); start = end - datetime.timedelta(days=days)
    hist = taifex.fetch_history(start, end)
    for d, rec in hist.items():
        old = db.get_meta(f"tx_futures:{d}") or {}
        if rec.get("day"): old["day"] = rec["day"]
        if rec.get("night"): old["night"] = rec["night"]
        db.set_meta(f"tx_futures:{d}", old)
    return len(hist)

def poll_once():
    codes = list(_stocks)
    if not codes: return 0
    q = realtime.quotes(codes + ["t00"], ttl=0, workers=3)
    n = 0
    with _lock:
        for c, qq in q.items():
            s = _stocks.get(c)
            if not s or not qq.get("live"): continue
            update_state(s, qq); n += 1
    if state["polls"] % 3 == 0: poll_futures()   # 每 15 秒更新期貨
    t = q.get("t00") or {}
    if t.get("price") and t.get("prev"):
        state["market"] = {"price": t["price"], "pct": round((t["price"] / t["prev"] - 1) * 100, 2), "open_pct": round((t["open"] / t["prev"] - 1) * 100, 2) if t.get("open") else None,
                           "high_pct": round((t["high"] / t["prev"] - 1) * 100, 2) if t.get("high") else None, "low_pct": round((t["low"] / t["prev"] - 1) * 100, 2) if t.get("low") else None, "time": t.get("time")}
    state.update(last_poll=datetime.datetime.now().strftime("%H:%M:%S"), polls=state["polls"] + 1)
    return n

def in_session(now=None):
    now = now or datetime.datetime.now()
    return now.weekday() < 5 and datetime.time(8, 57) <= now.time() <= datetime.time(13, 36)

_fut_sync_date = {}

def _loop():
    global _pool_date, _price_sync_date
    traded_today = False
    last_news = 0.0
    while True:
        try:
            now = datetime.datetime.now(); today = now.date().isoformat()
            # 即時新聞：盤前盤中每 15 分鐘抓一次 (鉅亨 / Google / Yahoo / 經濟日報)，其餘時間每小時
            busy = now.weekday() < 5 and datetime.time(7, 30) <= now.time() <= datetime.time(14, 30)
            if time.time() - last_news > (900 if busy else 3600):
                from . import sync
                if not sync.status.get("running"):
                    sync.start("news"); last_news = time.time()
            if now.weekday() < 5 and datetime.time(8, 30) <= now.time() < datetime.time(8, 57):
                if _fut_sync_date.get("hist") != today:
                    _fut_sync_date["hist"] = today
                    try: sync_futures_history(10)
                    except Exception as e: print("futures hist", e)
                poll_futures(); time.sleep(20); continue
            if in_session(now):
                if _pool_date != today:
                    _engine().get(); build_pool(); _pool_date = today; state["date"] = today; traded_today = False
                t0 = time.time()
                n = poll_once()
                live = n > 0
                state["trading"] = live
                if live:
                    traded_today = True
                    if state["polls"] % 12 == 0: save_state()
                time.sleep(max(1.0, DAYTRADE_POLL_SEC - (time.time() - t0)) if live else 30)
                continue
            state["trading"] = False
            if traded_today and now.time() >= datetime.time(13, 40) and not os.path.exists(os.path.join(DATA_DIR, "daytrade_bars", f"{today}.pkl")):
                try:
                    os.makedirs(os.path.join(DATA_DIR, "daytrade_bars"), exist_ok=True)
                    with _lock: dump = {c: {"name": st["name"], "prev": st["prev"], "open": st["open"], "yday": st.get("yday"), "bars": list(st["bars"])} for c, st in _stocks.items()}
                    with open(os.path.join(DATA_DIR, "daytrade_bars", f"{today}.pkl"), "wb") as f: pickle.dump({"date": today, "market": state.get("market"), "futures": state.get("futures"), "stocks": dump}, f)
                    try: sync_futures_history(5)
                    except Exception as e: print("futures hist", e)
                except Exception as e: print("archive bars", e)
            # 收盤後: 先確定今日行情已入庫 (14:40 後), 再抓分點做隔日判斷 (分點資料約 16:00~18:00 公布)
            if now.weekday() < 5 and now.time() >= datetime.time(14, 40) and _price_sync_date != today:   # 不看 traded_today：伺服器收盤後才啟動也要補抓今日行情，否則晚上不會建當日名單
                last = db.query("SELECT MAX(date) d FROM daily")[0]["d"]
                if (last or "") < today:
                    from . import sync
                    if sync.start("prices"): _price_sync_date = today
                else: _price_sync_date = today
            c = state["close"]
            target = _close_target_date()
            if target and c.get("date") != target and not c["running"] and (now.time() >= datetime.time(15, 30) or not traded_today or target < today):
                if (time.time() - _last_close_try.get(target, 0)) > 1200:
                    _last_close_try[target] = time.time()
                    build_close(target)
            time.sleep(30)
        except Exception as e:
            state["error"] = str(e); traceback.print_exc(); time.sleep(15)

_last_close_try = {}

def start():
    global _thread
    if _thread and _thread.is_alive(): return False
    state["started"] = datetime.datetime.now().strftime("%H:%M:%S")
    c = db.get_meta("daytrade_close") or {}
    state["close"].update(date=c.get("date"), built=c.get("built"))
    _thread = threading.Thread(target=_loop, daemon=True); _thread.start()
    return True

_news_cache = {"t": 0, "since": 0, "v": {}}
def news_recent(since_ts, until_ts=None, ttl=120):
    """近期有標記個股的新聞 -> {code: {"n", "sent", "title", "t"}} (sent = 最近一則的多空: 1/0/-1)。ttl 秒內重複呼叫用快取。"""
    now = time.time()
    if until_ts is None and now - _news_cache["t"] < ttl and _news_cache["since"] == since_ts: return _news_cache["v"]
    out = {}
    try:
        sql = "SELECT stocks, sentiment, title, published FROM news WHERE published>=? AND stocks != '[]' AND stocks IS NOT NULL"
        args = [since_ts]
        if until_ts is not None: sql += " AND published<=?"; args.append(until_ts)
        for r in db.query(sql + " ORDER BY published DESC", tuple(args)):
            try: codes = json.loads(r["stocks"] or "[]")
            except Exception: continue
            for c in codes:
                o = out.setdefault(c, {"n": 0, "sent": r["sentiment"], "title": r["title"], "t": r["published"], "bull": 0, "bear": 0})
                o["n"] += 1
                if r["sentiment"] == 1: o["bull"] += 1
                elif r["sentiment"] == -1: o["bear"] += 1
    except Exception as e: print("news_recent", e)
    if until_ts is None: _news_cache.update(t=now, since=since_ts, v=out)
    return out

def snapshot(limit=DAYTRADE_TOP, sort="heat", direction="", q="", min_lots=DAYTRADE_MIN_LOTS):
    """雷達清單 (已依 sort 排序)。min_lots: 前一交易日成交張數或今日累積量須達此門檻 (當沖流動性)。"""
    frac = session_fraction()
    items = []
    nw = news_recent(time.time() - 36 * 3600)   # 近 36 小時 (含前一晚) 有新聞的個股
    with _lock:
        for s in _stocks.values():
            m = metrics(s, frac)
            if not m or (s["volume"] or 0) < 100: continue
            if min_lots and (s["prev_lots"] or 0) < min_lots and (s["volume"] or 0) < min_lots: continue
            if direction and m["direction"] != direction: continue
            if q and q not in s["code"] and q not in s["name"]: continue
            bars = list(s["bars"])[-30:]
            items.append({"code": s["code"], "name": s["name"], "market": s["market"], "industry": s["industry"], "price": s["price"], "prev": s["prev"],
                          "open": s["open"], "high": s["high"], "low": s["low"], "volume": round(s["volume"] or 0), "prev_lots": s["prev_lots"],
                          "avg20_lots": s["avg20_lots"], "time": s["time"], "bid": s["bid"], "ask": s["ask"], "bid_vol": s["bid_vol"], "ask_vol": s["ask_vol"],
                          "amount": round((s["volume"] or 0) * 1000 * (s["vwap_num"] / s["vwap_den"] if s["vwap_den"] else s["price"])),
                          "yday": s["yday"], "news": nw.get(s["code"]), "spark": [[b["t"], b["c"], round(b["v"]), round(b["outer"] - b["inner"])] for b in bars], **m})
    keyf = {"heat": lambda x: x["heat"], "amp": lambda x: x["amp"], "pct": lambda x: x["pct"], "pct_down": lambda x: -x["pct"],
            "vol_ratio": lambda x: x["vol_ratio"] or 0, "outer": lambda x: x["outer_ratio"] or 0, "inner": lambda x: -(x["outer_ratio"] or 100),
            "net5": lambda x: x["net5"], "burst": lambda x: x["burst"] or 0, "volume": lambda x: x["volume"], "amount": lambda x: x["amount"],
            "book": lambda x: x["book"] or 0}.get(sort, lambda x: x["heat"])
    items.sort(key=lambda x: -keyf(x))
    return {"items": items[:limit], "total": len(items), "trading": state["trading"], "last_poll": state["last_poll"], "polls": state["polls"],
            "pool": state["pool"], "date": state["date"], "market": state.get("market"), "futures": state.get("futures"), "session_pct": round(frac * 100), "poll_sec": DAYTRADE_POLL_SEC, "started": state["started"], "min_lots": min_lots}

def bars(code):
    with _lock:
        s = _stocks.get(code)
        if not s: return None
        return {"code": code, "name": s["name"], "prev": s["prev"], "vwap": round(s["vwap_num"] / s["vwap_den"], 2) if s["vwap_den"] else None,
                "bars": [dict(b) for b in s["bars"]], "metrics": metrics(s)}

# ---------------------------------------------------------------- 收盤後: 隔日沖券商判斷
def _close_target_date():
    """要分析的交易日 = 資料庫最新行情日。"""
    r = db.query("SELECT MAX(date) d FROM daily")
    return r[0]["d"] if r and r[0]["d"] else None

def _candidates(date, limit=DAYTRADE_CLOSE_CANDIDATES):
    rows = db.query("SELECT d.code,s.name,s.market,s.industry,d.open,d.high,d.low,d.close,d.volume/1000.0 lots,d.amount, p.close prev "
                    "FROM daily d JOIN stocks s ON s.code=d.code LEFT JOIN daily p ON p.code=d.code AND p.date=(SELECT MAX(date) FROM daily WHERE date<? ) "
                    "WHERE d.date=? AND d.volume>=? AND d.amount>=5e7", (date, date, DAYTRADE_MIN_LOTS * 1000))
    dt = {r["code"]: r for r in db.query("SELECT code,dt_shares,dt_buy,dt_sell,flag FROM daytrade_stat WHERE date=?", (date,))}
    avg = {r["code"]: r["a"] for r in db.query("SELECT code, AVG(volume)/1000.0 a FROM daily WHERE date<? AND date>=date(?, '-30 day') GROUP BY code", (date, date))}
    prev2 = {}
    for r in db.query("SELECT code, close FROM daily WHERE date=(SELECT MAX(date) FROM daily WHERE date<(SELECT MAX(date) FROM daily WHERE date<?))", (date,)): prev2[r["code"]] = r["close"]
    c5 = {r["code"]: r["close"] for r in db.query("SELECT code, close FROM daily WHERE date=(SELECT date FROM (SELECT DISTINCT date FROM daily WHERE date<? ORDER BY date DESC LIMIT 1 OFFSET 4))", (date,))}
    d0 = datetime.datetime.fromisoformat(date)
    nw = news_recent(d0.replace(hour=6).timestamp(), (d0 + datetime.timedelta(days=1)).replace(hour=8, minute=30).timestamp())   # 名單日 06:00 ~ 隔日 08:30 的新聞
    fo = {r["code"]: (r["foreign_net"] or 0) / 1000 for r in db.query("SELECT code, foreign_net FROM insti WHERE date=?", (date,))}
    out = []
    for r in rows:
        if not is_stock_code(r["code"]) or not r["prev"] or not r["close"]: continue
        r["foreign"] = fo.get(r["code"])   # 張；法人資料約 16:00 公布，尚未入庫時為 None
        r["chg"] = round((r["close"] / r["prev"] - 1) * 100, 2)
        r["prev_chg"] = round((r["prev"] / prev2[r["code"]] - 1) * 100, 2) if prev2.get(r["code"]) else None
        r["amp"] = round(((r["high"] or r["close"]) - (r["low"] or r["close"])) / r["prev"] * 100, 2)
        r["avg20_lots"] = avg.get(r["code"]) or r["lots"]
        r["vol_ratio"] = round(r["lots"] / r["avg20_lots"], 2) if r["avg20_lots"] else None
        d = dt.get(r["code"])
        r["dt_lots"] = (d["dt_shares"] / 1000) if d else None
        r["dt_ratio"] = round(d["dt_shares"] / 1000 / r["lots"] * 100, 1) if d and r["lots"] else None
        r["dt_flag"] = (d["flag"] or "").strip() if d else ""
        r["chg5"] = round((r["close"] / c5[r["code"]] - 1) * 100, 2) if c5.get(r["code"]) else None
        n = nw.get(r["code"]); r["news_n"] = n["n"] if n else 0; r["news_sent"] = n["sent"] if n else None; r["news_title"] = n["title"] if n else None
        out.append(r)
    picked = {}
    def take(key, n, cond=lambda r: True):
        for r in sorted((x for x in out if cond(x)), key=key, reverse=True)[:n]: picked.setdefault(r["code"], r)
    take(lambda r: r["chg"], 200, lambda r: r["chg"] >= 3)
    take(lambda r: -r["chg"], 25, lambda r: r["chg"] <= -2.5)
    take(lambda r: r["vol_ratio"] or 0, 50, lambda r: (r["vol_ratio"] or 0) >= 1.5)
    take(lambda r: r["amp"], 40, lambda r: r["amp"] >= 4)
    take(lambda r: r["dt_ratio"] or 0, 40)
    take(lambda r: r["amount"], 40)
    for w in db.query("SELECT code FROM watchlist"):
        for r in out:
            if r["code"] == w["code"]: picked.setdefault(r["code"], r)
    lst = sorted(picked.values(), key=lambda r: -(abs(r["chg"]) * 3 + r["amp"] + (r["vol_ratio"] or 0) * 2 + (r["dt_ratio"] or 0) / 10))
    return lst[:limit]

def market_pct(date):
    """名單日大盤 (加權指數) 漲跌幅，沒有資料回 None。"""
    try:
        return ((db.get_meta(f"index:{date}") or {}).get("發行量加權股價指數") or {}).get("pct")
    except Exception: return None

def _tick(p):
    return 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1.0 if p < 1000 else 5.0

def limit_up_price(prev):
    """依證交所跳動單位計算漲停價 (prev*1.1 無條件捨去到該價位的 tick)。"""
    raw = prev * 1.1
    t = _tick(raw)
    return round((raw + 1e-9) // t * t, 2)

def judge(st, flows, patterns=OVERNIGHT_BROKERS, market_pct=None):
    """依券商分點買賣超判斷隔日偏多/偏空 (純函式)。
    st: {code,name,close,open,high,low,prev,chg,amp,lots,vol_ratio,dt_ratio}; flows: [{broker,buy,sell,net,pct}] (買超為正、賣超為負, 張)。"""
    lots = st.get("lots") or 0
    buys = sorted([f for f in flows if (f.get("net") or 0) > 0], key=lambda f: -f["net"])
    sells = sorted([f for f in flows if (f.get("net") or 0) < 0], key=lambda f: f["net"])
    # 外資分點 (美林/摩根大通) 在大型股 (成交金額 >= 30 億) 的買賣多為一般法人部位，不視為隔日沖 (旗標與合計一致)
    big = (st.get("amount") or 0) >= 3e9
    for f in buys + sells: f["overnight"] = broker.is_overnight(f["broker"], patterns) and not (big and broker.normalize_broker(f["broker"]) in ("美林", "摩根大通"))
    on_buy = sum(f["net"] for f in buys if f["overnight"])
    on_sell = -sum(f["net"] for f in sells if f["overnight"])
    on_buy_pct = on_buy / lots * 100 if lots else 0
    on_sell_pct = on_sell / lots * 100 if lots else 0
    top1 = buys[0] if buys else None
    top2 = buys[1] if len(buys) > 1 else None
    dominance = (top1["net"] / max(top2["net"], 1)) if top1 and top2 else (2.0 if top1 else 0)
    top1_on = bool(top1 and top1["overnight"])
    buy5_pct = sum(f.get("pct") or 0 for f in buys[:5])
    sell5_pct = sum(f.get("pct") or 0 for f in sells[:5])
    chg, amp = st.get("chg") or 0, st.get("amp") or 0
    hi, lo, close = st.get("high") or st["close"], st.get("low") or st["close"], st["close"]
    pos = (close - lo) / (hi - lo) if hi > lo else 0.5
    limit_up = bool(st.get("prev")) and close >= limit_up_price(st["prev"])
    dt_ratio = st.get("dt_ratio") or 0
    reasons, risks = [], []
    verdict, score = "watch", 0.0
    # ---- 偏空: 隔日沖券商進場 → 隔天開高出貨
    chg5 = st.get("chg5"); news_n = st.get("news_n") or 0; foreign = st.get("foreign")
    on_txt = f"隔日沖券商合計買超 {on_buy:,.0f} 張 (占成交量 {on_buy_pct:.1f}%)" if on_buy > 0 else "無明顯隔日沖券商買超"
    if chg >= 3 and market_pct is None:
        reasons.append(f"今日大漲 {chg:+.1f}%，{on_txt}；但名單日大盤漲跌尚未取得，無法判斷是否逆勢，先列觀察")
    elif chg >= 3 and market_pct < 0:
        reasons.append(f"今日大漲 {chg:+.1f}%，{on_txt}；但名單日大盤收跌 {market_pct:+.1f}%：逆勢大漲 = 有真實買盤，隔日續強機率高 (回測做空僅 44~56%)，不列做空")
        risks.append("若隔日開高後量縮、跌破開盤價再考慮盤中空")
    elif chg >= 3 and (limit_up or chg >= 7):
        reasons.append(f"今日大漲 {chg:+.1f}%{' 漲停' if limit_up else ''}，{on_txt}；漲幅過大 / 鎖漲停代表需求未被滿足，隔日續強機率高 (回測做空僅 54~60%)，不列做空")
        risks.append("漲停股隔日若開高不鎖、量能放大再找盤中空點")
    elif chg >= 3 and chg5 is not None and chg5 >= 10:
        reasons.append(f"今日大漲 {chg:+.1f}%，{on_txt}；但 5 日已漲 {chg5:+.1f}%，屬趨勢上攻股，隔日開高走低機率低 (回測做空僅 54%)，不列做空")
    elif chg >= 3:
        verdict = "short"
        # 成因：大盤收漲日全市場追價 → 短線籌碼 (當沖/隔日沖/散戶) 隔日開高即出貨；首次噴出 (5 日 <10%)、漲幅 3~7% 的股票最明顯
        # 回測 (全市場 66 日、179 檔)：75%，前後半期各 75%，逐月 70/74/82%；若隔日個股開高 0~3% 再執行，81% (隔日市場盤中下跌時) / 65% (市場盤中上漲時)
        score = 20 + (6 if chg < 5 else 0) + min(market_pct, 2) * 6 + (10 if buy5_pct < 15 else 0) + min(on_buy_pct, 5) * 2 + dt_ratio * 0.1 + min(st.get("amount") or 0, 5e9) / 1e9
        reasons.append(f"名單日大盤收漲 {market_pct:+.1f}%、個股漲 {chg:+.1f}% (非漲停)、5 日漲幅 {chg5 if chg5 is not None else 0:+.1f}%：追價資金隔日開高出貨 (回測 75%)")
        if on_buy > 0: reasons.append(on_txt + "，隔日沖籌碼增加隔日賣壓 (回測：對命中率影響不大，加分項)")
        if top1_on: reasons.append(f"買超第 1 名 {top1['broker']} 是隔日沖分點，買超是第 2 名的 {dominance:.1f} 倍")
        if buy5_pct < 15: reasons.append(f"買超前 5 名僅占 {buy5_pct:.1f}%，買盤分散 (散戶追價)，隔日開高走低機率較高 (回測 68%)")
        if foreign is not None and foreign <= 0: score += 8; reasons.append(f"外資賣超 {abs(foreign):,.0f} 張、散戶接手，隔日賣壓更重 (回測 74~86%)")
        if news_n: score += 10; reasons.append(f"當日上新聞 {news_n} 則「{(st.get('news_title') or '')[:30]}」：上新聞的大漲股隔日出貨機率高 (初步回測 20 檔 90%，樣本少)")
        if dt_ratio >= 40: reasons.append(f"當沖比 {dt_ratio:.0f}%，籌碼極短線")
        risks.append("執行條件：隔日開高 0～3% 再空 (回測 75%)；開高 >3% (54%) 或開平開低 (60%) 放棄。隔日大盤開低 >0.3% 當天不做")
        risks.append("隔日大盤盤中若轉強 (雷達上大盤翻紅、多數股站上均價) 命中率降到 65%，要縮手")
        if st.get("dt_flag"): risks.append("證交所註記暫停先賣後買當沖，無法現股放空")
    # ---- 偏多 A: 隔日沖倒貨完畢仍守住
    elif on_sell_pct >= 1.5 and chg >= -1.5 and pos >= 0.6 and not big and (st.get("vol_ratio") or 0) >= 1.2 and (st.get("prev_chg") or 0) >= 3:
        verdict = "watch"
        score = on_sell_pct * 6 + pos * 20 + max(chg, 0) * 2 + min(st.get("vol_ratio") or 1, 3) * 5
        reasons.append("隔日沖倒貨型偏多：回測 28 天做多命中僅 38%，不列建議做多，僅供觀察")
        reasons.append(f"前一日大漲 {st.get('prev_chg'):+.1f}% 隔日沖進場，今日隔日沖券商合計賣超 {on_sell:,.0f} 張 (占成交量 {on_sell_pct:.1f}%)，貨已倒出")
        reasons.append(f"股價仍收在當日區間 {pos * 100:.0f}% 位置{'、收紅 ' + f'{chg:+.1f}%' if chg > 0 else ''}，承接力道強 → 隔天賣壓減輕偏多")
        risks.append("若隔天開低破今日低點則多方架構失效")
    # ---- 偏多 B: 強勢股 + 買超集中 + 主力不是隔日沖
    elif chg >= 3 and on_buy_pct < 0.5 and not top1_on and pos >= 0.7 and (st.get("vol_ratio") or 0) >= 1.3 and buy5_pct >= 8:
        verdict = "watch"
        score = chg * 3 + buy5_pct + pos * 15 + min(st.get("vol_ratio") or 1, 4) * 5 + (10 if limit_up else 0)
        reasons.append("強勢股順勢型偏多：回測 28 天做多命中僅 38%，不列建議做多，僅供觀察")
        reasons.append(f"今日大漲 {chg:+.1f}%{' 漲停' if limit_up else ''}，收在區間高檔 ({pos * 100:.0f}%)，量比 {st.get('vol_ratio'):.1f}x")
        reasons.append(f"買超前 5 名合計 {buy5_pct:.1f}% 籌碼集中，且無隔日沖分點進場 → 隔天開高續攻機率較高，順勢做多")
        if top1: reasons.append(f"買超第 1 名 {top1['broker']} 買超 {top1['net']:,.0f} 張")
        risks.append("乖離過大時留意開高走低；開盤未過今日高點前不追")
    # ---- 偏空 B: 弱勢股帶量下跌、收在低檔、賣超集中 → 隔天反彈不過均價/開盤價續空
    elif chg <= -3 and pos <= 0.3 and (st.get("vol_ratio") or 0) >= 1.0 and sell5_pct >= 6:
        verdict = "watch"
        score = abs(chg) * 2 + sell5_pct + (1 - pos) * 15 + min(st.get("vol_ratio") or 1, 4) * 4 + on_sell_pct * 4
        reasons.append("弱勢股續跌型：回測 28 天 (172 檔) 隔日開→收下跌僅 44%、平均反彈 +0.4%，不列做空；只在反彈不過均價、內盤轉強時盤中找空點")
        reasons.append(f"今日大跌 {chg:+.1f}% 收在區間低檔 ({pos * 100:.0f}%)，量比 {st.get('vol_ratio'):.1f}x 帶量下跌")
        reasons.append(f"賣超前 5 名合計 {sell5_pct:.1f}% 籌碼集中出貨" + (f"，其中隔日沖分點賣超 {on_sell:,.0f} 張" if on_sell > 0 else ""))
        reasons.append("弱勢股慣性是隔天開高拉回或續跌：反彈到均價 / 開盤價不過、內盤轉強時做空")
        risks.append("跌深可能技術性反彈；開盤直接開低且量縮時不追空")
        if st.get("dt_flag"): risks.append("證交所註記暫停先賣後買當沖，無法現股放空")
    elif on_buy_pct >= 1.0 and chg > 0:
        reasons.append(f"隔日沖券商買超 {on_buy:,.0f} 張 ({on_buy_pct:.1f}%)，留意隔天開高後的出貨賣壓")
    elif on_sell_pct >= 1.0:
        reasons.append(f"隔日沖券商賣超 {on_sell:,.0f} 張 ({on_sell_pct:.1f}%) 出貨中")
    return {"verdict": verdict, "score": round(score, 1), "reasons": reasons, "risks": risks, "on_buy": round(on_buy), "on_buy_pct": round(on_buy_pct, 2),
            "on_sell": round(on_sell), "on_sell_pct": round(on_sell_pct, 2), "top1_overnight": top1_on, "dominance": round(dominance, 2), "buy5_pct": round(buy5_pct, 1), "sell5_pct": round(sell5_pct, 1),
            "pos": round(pos, 2), "limit_up": bool(limit_up),
            "buyers": [{"broker": f["broker"], "net": f["net"], "pct": f.get("pct"), "overnight": f["overnight"]} for f in buys[:5]],
            "sellers": [{"broker": f["broker"], "net": f["net"], "pct": f.get("pct"), "overnight": f["overnight"]} for f in sells[:5]]}

def _store_flows(code, date, parsed):
    rows = [(code, date, f["broker"], f["buy"], f["sell"], f["net"], f["pct"]) for f in parsed["buy"] + parsed["sell"] if f.get("broker")]
    db.executemany("DELETE FROM broker_flow WHERE code=? AND date=?", [(code, date)])
    if rows: db.executemany("INSERT OR REPLACE INTO broker_flow(code,date,broker,buy,sell,net,pct) VALUES(?,?,?,?,?,?,?)", rows)
    db.mark_fetched(f"broker:{code}", date, "ok" if rows else "empty")

def tag_items(items):
    """把當沖收盤判斷標到推薦/技術/籌碼名單上 (dt: verdict/date/on_buy_pct/on_sell_pct/chg)：同在做空名單的股票隔日開高常被倒貨，波段買點宜等拉回。"""
    try:
        rep = db.get_meta("daytrade_close") or {}
        tag = {}
        for kind in ("short", "long"):
            for x in rep.get(kind) or []:
                tag[x["code"]] = {"verdict": kind, "date": rep.get("date"), "on_buy_pct": x.get("on_buy_pct"), "on_sell_pct": x.get("on_sell_pct"), "chg": x.get("chg")}
        for it in items or []:
            if it.get("code") in tag: it["dt"] = tag[it["code"]]
    except Exception: pass
    return items

def build_close(date=None, force=False):
    """收盤後分析: 抓當沖統計 + 候選股分點 → 判斷隔日偏多/偏空，存到 meta daytrade_close。回傳 True 表示完成。"""
    c = state["close"]
    if c["running"]: return False
    date = date or _close_target_date()
    if not date: return False
    c.update(running=True, step="準備候選股", progress=0, total=0, error=None)
    try:
        d = datetime.date.fromisoformat(date)
        if not db.query("SELECT 1 FROM daytrade_stat WHERE date=? LIMIT 1", (date,)):
            c["step"] = "下載證交所/櫃買 當沖統計"
            rows, summ = broker.fetch_daytrade_stat(d)
            if rows: db.executemany("INSERT OR REPLACE INTO daytrade_stat(code,date,dt_shares,dt_buy,dt_sell,flag) VALUES(?,?,?,?,?,?)", rows)
            if summ: db.set_meta(f"daytrade_summary:{date}", summ)
        cands = _candidates(date)
        mkt = market_pct(date)
        if mkt is None:   # 法人同步 (約 16:00) 之前指數還沒入庫 → 直接向證交所補抓，否則做空規則無法判斷逆勢
            try:
                from .fetch import twse
                idx = twse.fetch_index_summary(d)
                if idx: db.set_meta(f"index:{date}", idx); mkt = market_pct(date)
            except Exception as e: print("index", date, e)
        c["step"] = "檢查分點資料是否已公布"
        probe = broker.fetch_broker("2330", date, sleep=0)
        if not probe["buy"] or probe.get("date") != date:
            c.update(step=f"{date} 券商分點資料尚未公布 (通常 16:00~18:00)，稍後自動重試", running=False); return False
        todo = [r for r in cands if force or db.fetched(f"broker:{r['code']}", date) != "ok"]
        c.update(step="下載券商分點進出", progress=0, total=len(todo))
        for i, r in enumerate(todo):
            try: _store_flows(r["code"], date, broker.fetch_broker(r["code"], date))
            except Exception as e: print("broker", r["code"], e)
            c["progress"] = i + 1
        c["step"] = "判斷隔日沖"
        flows = {}
        for f in db.query("SELECT code,broker,buy,sell,net,pct FROM broker_flow WHERE date=?", (date,)): flows.setdefault(f["code"], []).append(f)
        results = []
        for r in cands:
            fl = flows.get(r["code"])
            if not fl: continue
            j = judge(r, fl, market_pct=mkt)
            results.append({"code": r["code"], "name": r["name"], "market": r["market"], "industry": r["industry"], "close": r["close"], "open": r["open"], "prev_chg": r.get("prev_chg"), "chg5": r.get("chg5"), "foreign": r.get("foreign"), "news_n": r.get("news_n"), "news_sent": r.get("news_sent"), "news_title": r.get("news_title"),
                            "high": r["high"], "low": r["low"], "prev": r["prev"], "chg": r["chg"], "amp": r["amp"], "lots": round(r["lots"]), "amount": r["amount"],
                            "vol_ratio": r["vol_ratio"], "dt_ratio": r["dt_ratio"], "dt_flag": r["dt_flag"], **j})
        long_ = sorted([x for x in results if x["verdict"] == "long"], key=lambda x: -x["score"])
        short = sorted([x for x in results if x["verdict"] == "short"], key=lambda x: -x["score"])
        watch = sorted([x for x in results if x["verdict"] == "watch" and x["reasons"]], key=lambda x: -(x["on_buy_pct"] + x["on_sell_pct"]))
        out = {"date": date, "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "n_candidates": len(results), "market_pct": mkt, "long": long_[:40], "short": short[:40],
               "watch": watch[:40], "summary": db.get_meta(f"daytrade_summary:{date}"), "brokers": OVERNIGHT_BROKERS}
        db.set_meta("daytrade_close", out)
        db.set_meta(f"daytrade_close:{date}", {k: out[k] for k in ("date", "built", "long", "short")})
        c.update(step="完成", date=date, built=out["built"], running=False)
        # 更新盤中池的昨日資訊
        with _lock:
            for x in long_ + short:
                s = _stocks.get(x["code"])
                if s and date < datetime.date.today().isoformat():
                    s["yday"] = {"verdict": x["verdict"], "on_buy": x["on_buy"], "on_buy_pct": x["on_buy_pct"], "on_sell": x["on_sell"], "date": date}
        return True
    except Exception as e:
        c.update(error=str(e), running=False, step="錯誤"); traceback.print_exc(); return False

# ---------------------------------------------------------------- 名單驗證: 隔天實際走勢
def outcome(item, nxt):
    """單檔驗證 (純函式)。item: 名單項目 {verdict, close...}; nxt: 隔日 {open, high, low, close} (盤中時 close = 現價)。
    做空命中 = 開盤→收盤下跌；做多命中 = 開盤→收盤上漲。另算相對前收的漲跌、開盤跳空、盤中最大順向幅度。"""
    o, h, l, c, prev = nxt.get("open"), nxt.get("high"), nxt.get("low"), nxt.get("close"), item.get("close")
    if not o or not c or not prev: return None
    gap = (o / prev - 1) * 100; chg = (c / prev - 1) * 100; move = (c / o - 1) * 100
    short = item["verdict"] == "short"
    best = ((o / l - 1) * 100 if l else 0) if short else ((h / o - 1) * 100 if h else 0)   # 開盤後順向最大可得幅度
    return {"gap": round(gap, 2), "chg": round(chg, 2), "move": round(move, 2), "best": round(best, 2), "hit": move < 0 if short else move > 0}

def verify(days=20):
    """把最近 N 份每日名單對照隔一交易日的實際走勢 (DB 有隔日資料用 DB；隔日是今天且尚未入庫則用即時報價)。"""
    reports = []
    for r in db.query("SELECT key, value FROM meta WHERE key LIKE 'daytrade_close:%' ORDER BY key DESC LIMIT ?", (days,)):
        try: reports.append(json.loads(r["value"]))
        except Exception: pass
    if not reports: return {"days": [], "summary": {}}
    dates = [r["date"] for r in db.query("SELECT DISTINCT date FROM daily ORDER BY date")]
    today = datetime.date.today().isoformat()
    live = {}
    out_days, agg = [], {"long": [], "short": [], "short_a": [], "short_b": [], "short_exec": [], "short_exec_futup": []}
    for rep in reports:
        d = rep["date"]
        later = [x for x in dates if x > d]
        nxt_date, src, bars = (later[0], "收盤", None) if later else (None, None, None)
        if nxt_date:
            bars = {r["code"]: r for r in db.query("SELECT code,open,high,low,close FROM daily WHERE date=?", (nxt_date,))}
        elif d < today and (state["trading"] or state["last_poll"]):
            codes = [x["code"] for x in rep["long"] + rep["short"]]
            if codes and not live: live = realtime.quotes(codes, ttl=30, workers=3)
            bars = {c: {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["price"]} for c, q in live.items() if q.get("live")}
            nxt_date, src = today, "盤中即時"
        if not bars: out_days.append({"date": d, "next": None, "items": [], "note": "隔日資料尚未取得"}); continue
        fut_next = futures_pct(nxt_date) if nxt_date else {}
        items = []
        for kind in ("long", "short"):
            for x in rep[kind]:
                o = outcome(x, bars.get(x["code"]) or {})
                if not o: continue
                rule = kind if kind == "long" else ("short_b" if x["chg"] < 0 else "short_a")
                it = {"code": x["code"], "name": x["name"], "verdict": kind, "rule": rule, "score": x["score"], "prev_close": x["close"], "reason": (x["reasons"] or [""])[0], **o}
                it["exec"] = kind == "short" and 0 < o["gap"] <= 3
                items.append(it); agg[kind].append(o)
                if kind == "short": agg[rule].append(o)
                if it["exec"]: agg["short_exec"].append(o)
                if it["exec"] and fut_next.get("open_pct") is not None and fut_next["open_pct"] > 1: agg["short_exec_futup"].append(o)
        out_days.append({"date": d, "next": nxt_date, "src": src, "items": items, "fut_night_pct": futures_pct(d).get("night_pct"), "fut_open_pct": fut_next.get("open_pct"), "market_pct": market_pct(d), "next_market_pct": market_pct(nxt_date) if nxt_date and nxt_date != today else None,
                         "long_hit": sum(1 for i in items if i["verdict"] == "long" and i["hit"]), "long_n": sum(1 for i in items if i["verdict"] == "long"),
                         "short_hit": sum(1 for i in items if i["verdict"] == "short" and i["hit"]), "short_n": sum(1 for i in items if i["verdict"] == "short")})
    def summ(lst):
        if not lst: return None
        return {"n": len(lst), "hit": sum(1 for o in lst if o["hit"]), "win": round(sum(1 for o in lst if o["hit"]) / len(lst) * 100),
                "avg_move": round(sum(o["move"] for o in lst) / len(lst), 2), "avg_chg": round(sum(o["chg"] for o in lst) / len(lst), 2), "avg_best": round(sum(o["best"] for o in lst) / len(lst), 2)}
    return {"days": out_days, "summary": {k: summ(v) for k, v in agg.items()}}

def close_report():
    rep = db.get_meta("daytrade_close") or {}
    return {"report": rep, "status": state["close"], "target_date": _close_target_date()}

def start_close_build(force=False):
    if state["close"]["running"]: return False
    threading.Thread(target=build_close, kwargs={"force": force}, daemon=True).start()
    return True
