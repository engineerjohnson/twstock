"""新聞規則分析: 利多/利空判斷、關聯個股、主題標籤。"""
import re, json, time
from .. import db

BULL = {  # keyword: weight
    "漲停": 3, "大漲": 2, "創新高": 2, "新高": 1, "接單": 2, "訂單": 2, "滿載": 2, "塞爆": 2, "上修": 3, "調升": 2, "調高": 2, "看好": 1,
    "擴產": 2, "需求強勁": 2, "需求暢旺": 2, "營收創": 2, "獲利": 1, "買超": 2, "加碼": 2, "轉單": 2, "得標": 2, "補漲": 1,
    "目標價": 1, "突破": 1, "回升": 1, "回溫": 1, "旺季": 1, "漲價": 2, "報喜": 2, "利多": 3, "成長": 1, "翻倍": 3, "倍增": 3,
    "大單": 2, "急單": 2, "認購": 1, "庫藏股": 2, "合作": 1, "打入": 2, "供應鏈": 1, "出貨": 1, "放量": 1, "法人買": 2,
    "反彈": 1, "強勢": 1, "亮眼": 2, "優於預期": 3, "超乎預期": 3, "超預期": 3, "年增": 1, "增持": 2, "擴大": 1, "受惠": 2,
    "題材": 1, "獨家": 1, "佈局": 1, "布局": 1, "降息": 2, "資金行情": 2, "連買": 2, "連續買超": 2, "大買": 3, "搶進": 2, "站上": 1,
    "創高": 2, "新訂單": 2, "缺貨": 2, "供不應求": 3, "調薪": 0, "EPS上修": 3, "上調": 2, "喊買": 2, "進駐": 1, "回神": 1,
}
BEAR = {
    "跌停": 3, "重挫": 3, "崩跌": 3, "大跌": 2, "下修": 3, "調降": 2, "衰退": 2, "虧損": 2, "賣超": 2, "裁員": 2, "關稅": 2, "制裁": 2,
    "減產": 1, "砍單": 3, "失守": 2, "恐慌": 2, "降評": 2, "跌破": 2, "做空": 1, "禁令": 2, "停工": 2, "戰爭": 2, "利空": 3,
    "衰減": 2, "下滑": 1, "減少": 1, "年減": 1, "縮減": 1, "倒閉": 3, "違約": 2, "調查": 1, "罰款": 1, "延後": 1, "遞延": 1,
    "不如預期": 3, "低於預期": 3, "疲弱": 2, "疲軟": 2, "賣壓": 2, "拋售": 2, "出脫": 2, "減持": 2, "示警": 2, "警訊": 2,
    "連賣": 2, "連續賣超": 2, "升息": 1, "通膨": 1, "泡沫": 2, "殺盤": 2, "跳水": 2, "重摔": 2, "慘": 1, "崩": 2, "暴跌": 3,
    "提款": 1, "狂瀉": 3, "血洗": 3, "休市": 0, "颱風": 0, "降息預期降溫": 2, "鷹派": 1, "獲利了結": 1,
}
TOPICS = {
    "訂單/接單": ["訂單", "接單", "滿載", "急單", "大單", "轉單", "得標", "砍單", "拉貨"],
    "EPS/獲利": ["EPS", "每股盈餘", "獲利", "稅後", "淨利", "毛利", "本益比"],
    "營收": ["營收"],
    "擴產/資本支出": ["擴產", "資本支出", "建廠", "新廠", "產能"],
    "法說/展望": ["法說", "展望", "財測", "法說會", "財報"],
    "法人動向": ["外資", "投信", "自營", "三大法人", "買超", "賣超", "八大公股", "大戶", "主力", "籌碼"],
    "AI/半導體": ["AI", "輝達", "NVIDIA", "台積", "半導體", "晶片", "CoWoS", "HBM", "伺服器", "GPU", "先進封裝", "矽光子", "記憶體"],
    "總經/聯準會": ["聯準會", "Fed", "利率", "降息", "升息", "通膨", "CPI", "非農", "GDP", "央行"],
    "關稅/地緣": ["關稅", "川普", "中美", "地緣", "制裁", "出口管制", "戰爭", "中東", "台海"],
    "匯率": ["匯率", "台幣", "美元", "日圓", "貶值", "升值"],
    "美股/國際": ["美股", "費半", "那斯達克", "道瓊", "標普", "日經", "韓股", "台積電ADR", "ADR"],
    "航運/傳產": ["航運", "貨櫃", "運價", "鋼鐵", "塑化", "水泥", "紡織"],
    "金融": ["金控", "銀行", "壽險", "保險", "證券"],
    "生技": ["生技", "新藥", "FDA", "解盲", "藥證"],
}
PRE_MARKET = ["盤前", "開盤前", "早盤", "開盤"]
POST_MARKET = ["盤後", "收盤", "終場", "尾盤", "今日台股", "台股今"]

_name_map = None
STOP_NAMES = {"中華", "台灣", "亞洲", "中國", "美國", "日本", "國際", "和平", "中央", "世界", "東方", "全球", "精英", "聯合", "第一",
              "上海", "台北", "新光", "開發", "信義", "中信", "富邦", "國泰", "永豐", "元大", "台新", "玉山", "兆豐", "地球", "大量", "力士",
              "新興", "三星", "國建", "中工", "至上", "時碩", "網家", "中環", "遠東", "華南", "大成", "美律", "光明", "正新", "泰山", "福懋",
              "全台", "全新", "大眾", "台達", "世界", "長華", "高技", "大聯", "友通", "全漢", "其陽", "立端", "公準", "愛普", "全新", "環宇", "正文", "友勁"}
# 常見且不易誤判的 2 字簡稱 (直接比對)；其餘 2 字簡稱需有股市語境
SAFE2 = set("""鴻海 聯電 友達 群創 台塑 南亞 台化 中鋼 華碩 廣達 緯創 仁寶 和碩 光寶 聯詠 瑞昱 創意 世芯 欣興 南電 景碩 健鼎 台燿 聯茂
緯穎 奇鋐 雙鴻 健策 川湖 智邦 穎崴 致茂 力成 南茂 旺宏 群聯 威剛 十銓 創見 漢唐 帆宣 亞翔 聖暉 東元 士電 華城 亞力 長榮 萬海 陽明
裕民 慧洋 華航 台泥 亞泥 儒鴻 聚陽 統一 中租 國巨 華新 大同 東台 上銀 研華 樺漢 信驊 譜瑞 祥碩 智原 立積 穩懋 宏碁 微星 技嘉 神達
神基 緯軟 零壹 精誠 敦陽 牧德 由田 京鼎 弘塑 辛耘 萬潤 均豪 盟立 志聖 家登 翔名 崇越 鈊象 精材 勤誠 營邦 建準 定穎 博智 嘉澤 富喬
德宏 臻鼎 燿華 高技 敬鵬 瀚宇 旭隼 台達 聯強 文曄 大聯 至上 緯穎 廣運 所羅門 系統電 艾笛森 光聖 上詮 波若威 聯鈞 華星光 眾達 聯亞
漢磊 嘉晶 茂矽 中美晶 環球晶 合晶 台勝科 力積電 世界 聯發科 大立光 玉晶光 亞光 今國光 先進光 鴻準 可成 和大 台玻 長興 永光 台肥
中碳 台塑化 遠傳 台哥大 中華電 宏達電 宏碁 緯創 英業達 新普 順達 加百裕 西勝 台表科 景碩 南電 欣興 川湖 嘉澤 勤誠 營邦 貿聯 
矽力 信邦 良維 健和興 全漢 台達電 光寶科 群電 康舒 僑威 高力 奇鋐 雙鴻 建準 健策 兆利 新日興 鑫禾 金像電 博智 定穎 華通 楠梓電
欣興 台光電 聯茂 台燿 騰輝 富喬 德宏 國精化 長華 日月光 矽品 京元電 力成 南茂 欣銓 典範 菱生 華泰 同欣電 精材 穎崴 旺矽 雍智
中探針 和碩 仁寶 廣達 緯穎 神達 神基 英業達 技嘉 微星 華碩 鴻海 宏碁 大眾 友通 研揚 凌華 樺漢 研華 振樺 飛捷 其陽 立端 零壹
精誠 敦陽 資通 叡揚 伊雲谷 安碁 關貿 凌群 大世科 中菲 公準 漢唐 帆宣 亞翔 聖暉 朋億 鼎基 京鼎 弘塑 辛耘 萬潤 均豪 盟立 志聖
家登 翔名 崇越 創意 世芯 智原 M31 愛普 晶心科 力旺 信驊 譜瑞 祥碩 聯詠 瑞昱 聯發科 立積 穩懋 宏捷科 全新 環宇 昇達科 啟碁 智易
明泰 中磊 正文 合勤 智邦 友勁 台揚 鈺太 矽統 威盛 聯陽 盛群 松翰 凌通 義隆 原相 敦泰 矽創 天鈺 晶豪科 鈺創 南亞科 華邦電 旺宏
群聯 威剛 創見 十銓 宇瞻 宜鼎 慧榮 點序 安國 鈺寶 台積電""".split())
STOCK_CTX = r"(股價|股|漲停|跌停|法說|營收|EPS|買超|賣超|目標價|訂單|接單|飆|噴|亮燈|攻|漲|跌|獲利|出貨|擴產|評等|喊進|看好|加碼|調升|調降|法人|外資|投信|大戶|主力|籌碼)"

def name_map(refresh=False):
    global _name_map
    if _name_map is None or refresh:
        rows = db.query("SELECT code,name FROM stocks WHERE name<>''")
        pairs = [(r["name"], r["code"]) for r in rows if len(r["name"]) >= 2 and r["name"] not in STOP_NAMES]
        pairs.sort(key=lambda kv: -len(kv[0]))
        _name_map = dict(pairs)
    return _name_map

def find_stocks(text, hint=None, keywords=None):
    found = []
    for c in (hint or []):
        if c not in found: found.append(c)
    for m in re.finditer(r"(?<!\d)([1-9]\d{3})(?:-TW|-TWO|\)|）)", text):
        if m.group(1) not in found: found.append(m.group(1))
    nm = name_map()
    if not hasattr(find_stocks, "_codes"):
        find_stocks._codes = set(r["code"] for r in db.query("SELECT code FROM stocks"))
    codes = find_stocks._codes
    for kw in (keywords or []):
        c = nm.get(str(kw).strip())
        if c and c not in found: found.append(c)
    for name, code in nm.items():
        if code in found or name not in text: continue
        ok = len(name) >= 3 or name in SAFE2
        if not ok:
            ok = re.search(re.escape(name) + r".{0,6}" + STOCK_CTX, text) is not None or                  re.search(STOCK_CTX + r".{0,6}" + re.escape(name), text) is not None
        if ok:
            found.append(code)
            text = text.replace(name, " ")  # 避免子字串重複 (台積電 / 台積)
    return [c for c in found if c in codes][:8]

def score(text):
    s = 0; hits_b, hits_r = [], []
    for k, w in BULL.items():
        if k in text: s += w; hits_b.append(k)
    for k, w in BEAR.items():
        if k in text: s -= w; hits_r.append(k)
    return s, hits_b, hits_r

def classify(item):
    text = f"{item['title']} {item.get('summary','')} {item.get('content','')[:400]}"
    s, hb, hr = score(item["title"] + " " + item["title"] + " " + item.get("summary", "")[:200])  # title weighs double
    tags = [t for t, kws in TOPICS.items() if any(k.lower() in text.lower() for k in kws)]
    if any(k in item["title"] for k in PRE_MARKET): tags.append("盤前")
    if any(k in item["title"] for k in POST_MARKET): tags.append("盤後")
    sentiment = 1 if s >= 2 else (-1 if s <= -2 else 0)
    stocks = find_stocks(text, item.get("stocks_hint"), item.get("keywords"))
    # extract headline numbers e.g. "EPS 上修至 12 元", "年增 3 倍"
    m = re.findall(r"(EPS[^，。,]{0,20}?\d+(?:\.\d+)?\s*(?:元|倍)|年增\s*\d+(?:\.\d+)?\s*(?:%|倍|成)|成長\s*\d+(?:\.\d+)?\s*(?:%|倍|成)|目標價[^，。,]{0,12}?\d+(?:\.\d+)?\s*元)", text)
    highlights = list(dict.fromkeys(m))[:3]
    return {"sentiment": sentiment, "score": s, "bull": hb[:6], "bear": hr[:6], "tags": list(dict.fromkeys(tags)), "stocks": stocks, "highlights": highlights}

def store(items):
    now = int(time.time())
    rows = []
    for it in items:
        c = classify(it)
        tags = {"topics": c["tags"], "bull": c["bull"], "bear": c["bear"], "score": c["score"], "highlights": c["highlights"], "keywords": it.get("keywords", [])[:8]}
        rows.append((it["id"], it["source"], it["category"], it["title"], it["link"], it["published"], it.get("summary", "")[:600],
                     json.dumps(c["stocks"]), c["sentiment"], json.dumps(tags, ensure_ascii=False), now))
    before = db.query("SELECT COUNT(*) n FROM news")[0]["n"]
    db.executemany("INSERT OR REPLACE INTO news(id,source,category,title,link,published,summary,stocks,sentiment,tags,fetched) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
    # keep 14 days
    db.executemany("DELETE FROM news WHERE published < ?", [(now - 14 * 86400,)])
    after = db.query("SELECT COUNT(*) n FROM news")[0]["n"]
    return max(0, after - before)
