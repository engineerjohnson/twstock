import sqlite3, json, threading
from .config import DB_PATH

_lock = threading.RLock()

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks(code TEXT PRIMARY KEY, name TEXT, market TEXT, industry TEXT);
CREATE TABLE IF NOT EXISTS daily(code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL, txn REAL, PRIMARY KEY(code,date));
CREATE INDEX IF NOT EXISTS idx_daily_date ON daily(date);
CREATE TABLE IF NOT EXISTS insti(code TEXT, date TEXT, foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
    PRIMARY KEY(code,date));
CREATE INDEX IF NOT EXISTS idx_insti_date ON insti(date);
CREATE TABLE IF NOT EXISTS fundamentals(code TEXT PRIMARY KEY, rev_month TEXT, rev REAL, rev_mom REAL, rev_yoy REAL,
    rev_cum_yoy REAL, eps_q REAL, eps_year TEXT, eps_season TEXT, net_income REAL, pe REAL, pb REAL, yield REAL, updated TEXT);
CREATE TABLE IF NOT EXISTS tdcc(code TEXT, date TEXT, level INTEGER, holders INTEGER, shares REAL, pct REAL,
    PRIMARY KEY(code,date,level));
CREATE TABLE IF NOT EXISTS news(id TEXT PRIMARY KEY, source TEXT, category TEXT, title TEXT, link TEXT,
    published INTEGER, summary TEXT, stocks TEXT, sentiment INTEGER, tags TEXT, fetched INTEGER);
CREATE INDEX IF NOT EXISTS idx_news_pub ON news(published);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS margin(code TEXT, date TEXT, fin_balance REAL, fin_change REAL, short_balance REAL, short_change REAL,
    PRIMARY KEY(code,date));
CREATE INDEX IF NOT EXISTS idx_margin_date ON margin(date);
CREATE TABLE IF NOT EXISTS watchlist(code TEXT PRIMARY KEY, added TEXT, note TEXT, alert_above REAL, alert_below REAL);
CREATE TABLE IF NOT EXISTS fetch_log(kind TEXT, date TEXT, status TEXT, PRIMARY KEY(kind,date));
"""

def init():
    with _lock:
        con = connect()
        con.executescript(SCHEMA)
        con.commit(); con.close()

def get_meta(key, default=None):
    con = connect()
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    con.close()
    if row is None: return default
    try: return json.loads(row["value"])
    except Exception: return row["value"]

def set_meta(key, value):
    with _lock:
        con = connect()
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
        con.commit(); con.close()

def executemany(sql, rows):
    if not rows: return 0
    with _lock:
        con = connect()
        con.executemany(sql, rows)
        con.commit(); n = con.total_changes; con.close()
    return n

def query(sql, params=()):
    con = connect()
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    return rows

def fetched(kind, date):
    con = connect()
    r = con.execute("SELECT status FROM fetch_log WHERE kind=? AND date=?", (kind, date)).fetchone()
    con.close()
    return r["status"] if r else None

def mark_fetched(kind, date, status):
    executemany("INSERT OR REPLACE INTO fetch_log(kind,date,status) VALUES(?,?,?)", [(kind, date, status)])
