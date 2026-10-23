import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(DATA_DIR, "twstock.db")
os.makedirs(DATA_DIR, exist_ok=True)
# 雲端部署時若 data 目錄是空的，複製隨附的資料庫快照 (省去第一次 5 分鐘下載)
_seed = os.path.join(BASE_DIR, "data", "twstock.db")
if not os.path.exists(DB_PATH) and os.path.exists(_seed) and os.path.abspath(_seed) != os.path.abspath(DB_PATH):
    import shutil; shutil.copy(_seed, DB_PATH)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()   # 設定後需輸入密碼才能使用 (雲端公開網址用)
PORT = int(os.environ.get("PORT", "8765"))

HISTORY_DAYS = 90          # calendar days of daily K to keep/fetch initially (~60 trading days)
INSTI_DAYS = 35            # calendar days of institutional data (~25 trading days)
REQUEST_SLEEP = 0.7        # seconds between TWSE/TPEx requests (be polite, avoid blocks)
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                "Accept-Language": "zh-TW,zh;q=0.9"}
