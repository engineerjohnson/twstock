"""新聞來源: 鉅亨網 API (含相關個股), Google News RSS, Yahoo 股市 RSS, 經濟日報 RSS."""
import re, time, html, hashlib, calendar
from urllib.parse import quote
import feedparser
from .common import get
from .. import db

CNYES_CATS = {  # category -> our category label
    "tw_quo": "盤前盤後", "tw_stock": "台股", "tw_stock_news": "台股", "tw_macro": "總經", "us_stock": "美股",
    "wd_stock": "國際", "headline": "頭條", "tw_insurance": "台股",
}
GOOGLE_QUERIES = ["台股 盤前", "台股 盤後", "外資 買超", "投信 買超", "台積電", "美股 收盤 台股", "聯準會 利率", "半導體 訂單",
                  "法說會 展望", "EPS 上修", "AI 伺服器 台廠", "關稅 台灣", "大戶 加碼", "主力 買超", "營收 創新高"]
RSS = {
    "Yahoo股市-台股": ("https://tw.stock.yahoo.com/rss?category=tw-market", "台股"),
    "Yahoo股市-國際": ("https://tw.stock.yahoo.com/rss?category=intl-markets", "國際"),
    "經濟日報-證券": ("https://money.udn.com/rssfeed/news/1001/5590?ch=money", "台股"),
    "經濟日報-國際": ("https://money.udn.com/rssfeed/news/1001/5588?ch=money", "國際"),
}

def _clean(s):
    s = html.unescape(html.unescape(s or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def _id(link, title):
    return hashlib.md5((link or title).encode("utf-8")).hexdigest()[:16]

def fetch_cnyes(limit=30):
    items = []
    for cat, label in CNYES_CATS.items():
        try:
            j = get(f"https://api.cnyes.com/media/api/v1/newslist/category/{cat}?limit={limit}", timeout=25, sleep=0.3).json()
            for it in j.get("items", {}).get("data", []):
                nid = str(it.get("newsId"))
                link = f"https://news.cnyes.com/news/id/{nid}"
                content = _clean(it.get("content", ""))[:1200]
                summary = _clean(it.get("summary") or "")
                if len(content) > len(summary):  # 摘要常只有一句；改用內文前 600 字 (切在句尾)，播報時才唸得完整
                    cut = content[:600]
                    m = re.search(r"^.*[。！？]", cut, re.S)
                    summary = (m.group(0) if m and len(m.group(0)) >= 120 else cut) or summary
                stocks = [s for s in (it.get("stock") or []) if re.fullmatch(r"\d{4}", str(s))]
                items.append({"id": "cnyes" + nid, "source": "鉅亨網", "category": label, "title": _clean(it.get("title")),
                              "link": link, "published": int(it.get("publishAt") or time.time()), "summary": summary,
                              "stocks_hint": stocks, "keywords": it.get("keyword") or [], "content": content})
        except Exception as e:
            print("cnyes", cat, e)
    return items

def _parse_feed(content, source, label):
    f = feedparser.parse(content)
    items = []
    for e in f.entries:
        title = _clean(e.get("title", ""))
        if not title: continue
        link = e.get("link", "")
        ts = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                ts = calendar.timegm(e[k]); break
        src = source
        if isinstance(e.get("source"), dict) and e["source"].get("title"):
            src = e["source"]["title"]
            title = re.sub(r"\s*-\s*" + re.escape(src) + r"\s*$", "", title)
        items.append({"id": _id(link, title), "source": src, "category": label, "title": title, "link": link,
                      "published": ts or int(time.time()), "summary": _clean(e.get("summary", ""))[:400], "stocks_hint": [],
                      "keywords": [], "content": ""})
    return items

def fetch_google(queries=GOOGLE_QUERIES):
    items = []
    for q in queries:
        try:
            r = get(f"https://news.google.com/rss/search?q={quote(q)}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant", timeout=25, sleep=0.3)
            label = "國際" if any(k in q for k in ("美股", "聯準會")) else "台股"
            items += _parse_feed(r.content, "GoogleNews", label)
        except Exception as e:
            print("google", q, e)
    return items

def fetch_rss():
    items = []
    for name, (url, label) in RSS.items():
        try:
            r = get(url, timeout=25, sleep=0.3)
            items += _parse_feed(r.content, name, label)
        except Exception as e:
            print("rss", name, e)
    return items

def fetch_all(progress=None):
    all_items = []
    for i, fn in enumerate((fetch_cnyes, fetch_rss, fetch_google)):
        all_items += fn()
        if progress: progress(i + 1, 3)
    # de-dup by id and near-identical titles
    seen, out, titles = set(), [], set()
    for it in sorted(all_items, key=lambda x: -x["published"]):
        key = re.sub(r"[\s\W]+", "", it["title"])[:30]
        if it["id"] in seen or key in titles: continue
        seen.add(it["id"]); titles.add(key); out.append(it)
    return out
