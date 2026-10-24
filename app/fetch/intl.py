"""國際市場 (yfinance): 美股、費半、台積電ADR、VIX、匯率、亞股、原油."""
import datetime, math
import yfinance as yf
from .. import db

TICKERS = {
    "^GSPC": "S&P 500", "^DJI": "道瓊", "^IXIC": "那斯達克", "^SOX": "費城半導體", "TSM": "台積電ADR", "NVDA": "輝達",
    "AMD": "AMD", "AVGO": "博通", "MU": "美光", "AAPL": "蘋果", "^VIX": "VIX恐慌指數", "USDTWD=X": "美元/台幣",
    "^N225": "日經225", "^KS11": "韓國KOSPI", "^HSI": "恆生", "CL=F": "WTI原油", "^TNX": "美10年債殖利率",
    "^TWII": "台灣加權", "EWT": "台灣ETF(EWT)", "DX-Y.NYB": "美元指數",
}

def update(period="3mo"):
    data = yf.download(list(TICKERS), period=period, interval="1d", group_by="ticker", threads=True, progress=False, auto_adjust=False)
    out = {}
    for t, name in TICKERS.items():
        try:
            s = data[t]["Close"].dropna()
            if len(s) < 2: continue
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            hist = [{"date": str(i.date()), "close": round(float(v), 2)} for i, v in s.tail(60).items()]
            pct = (last / prev - 1) * 100 if prev else 0
            w5 = (last / float(s.iloc[-6]) - 1) * 100 if len(s) > 6 else None
            out[t] = {"name": name, "close": round(last, 2), "prev": round(prev, 2), "change": round(last - prev, 2),
                      "pct": round(pct, 2), "pct5d": round(w5, 2) if w5 is not None else None, "date": str(s.index[-1].date()),
                      "hist": hist}
        except Exception as e:
            print("intl", t, e)
    out["_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    db.set_meta("intl", out)
    return out

def fetch_stock_history(code, market, period="1y"):
    """Fallback per-stock history from Yahoo (used for K線 when local history is short)."""
    suffix = ".TW" if market == "TWSE" else ".TWO"
    df = yf.download(f"{code}{suffix}", period=period, interval="1d", progress=False, auto_adjust=False)
    if df is None or df.empty: return []
    if hasattr(df.columns, "levels"): df.columns = df.columns.get_level_values(0)
    rows = []
    for i, r in df.iterrows():
        if any(isinstance(r[k], float) and math.isnan(r[k]) for k in ("Open", "High", "Low", "Close")): continue
        if not r["Volume"] or (isinstance(r["Volume"], float) and math.isnan(r["Volume"])): continue  # 休市日佔位列 (量 0) 不要
        rows.append((code, str(i.date()), float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
                     float(r["Volume"]), None, None))
    return rows
