import requests, time, re, datetime
from ..config import HTTP_HEADERS, REQUEST_SLEEP

_session = requests.Session()
_session.headers.update(HTTP_HEADERS)

def get(url, retries=3, timeout=40, sleep=REQUEST_SLEEP, **kw):
    last = None
    for i in range(retries):
        try:
            r = _session.get(url, timeout=timeout, **kw)
            if r.status_code == 200:
                if sleep: time.sleep(sleep)
                return r
            last = Exception(f"HTTP {r.status_code}")
        except Exception as e:
            last = e
        time.sleep(2 + i * 2)
    raise last

def get_json(url, **kw):
    r = get(url, **kw)
    return r.json()

def num(s):
    """Parse TWSE/TPEx numeric strings ('1,234', '--', '', '+5.00')."""
    if s is None: return None
    if isinstance(s, (int, float)): return float(s)
    s = re.sub(r"<[^>]+>", "", str(s)).strip().replace(",", "")
    if s in ("", "--", "-", "---", "X", "除權", "除息", "N/A", "NA"): return None
    try: return float(s)
    except ValueError: return None

def is_stock_code(code):
    """Common stocks only: 4 digits, not ETF (00xx), no suffix letters."""
    return bool(re.fullmatch(r"[1-9]\d{3}", code or ""))

def roc_to_iso(s):
    """'115/10/22' or '1151022' -> '2026-10-22'"""
    s = str(s).strip()
    m = re.match(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = re.match(r"(\d{3})(\d{2})(\d{2})$", s)
    if m:
        return f"{int(m.group(1))+1911:04d}-{m.group(2)}-{m.group(3)}"
    return s

def ymd(d):  # date -> '20261022'
    return d.strftime("%Y%m%d")

def iso(d):  # date -> '2026-10-22'
    return d.strftime("%Y-%m-%d")

def weekdays_back(n_calendar_days, end=None):
    """Weekdays (Mon-Fri) from today back n calendar days, newest first."""
    end = end or datetime.date.today()
    out = []
    for i in range(n_calendar_days + 1):
        d = end - datetime.timedelta(days=i)
        if d.weekday() < 5:
            out.append(d)
    return out
