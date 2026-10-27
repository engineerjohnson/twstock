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
REC_MIN_DAY_LOTS = 10000  # 推薦股 / 技術面起漲: 前一交易日成交量需 >= 1 萬張才列入
REQUEST_SLEEP = 0.7        # seconds between TWSE/TPEx requests (be polite, avoid blocks)
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36",
                "Accept-Language": "zh-TW,zh;q=0.9"}

# ===== 當沖雷達 =====
DAYTRADE_POLL_SEC = 5        # 盤中輪詢證交所 MIS 的間隔 (秒)
DAYTRADE_POOL_SIZE = 260     # 盤中掃描池大小 (依前一交易日成交金額排序；每 50 檔一次請求)
DAYTRADE_POOL_MIN_LOTS = 10000  # 進掃描池的前一交易日最低成交張數 (當沖需要流動性, 1 萬張以上才能即時進出)
DAYTRADE_MIN_LOTS = 10000       # 雷達 / 收盤後名單的成交張數門檻 (前一日或今日累積量達標即可)
DAYTRADE_TOP = 100           # 雷達畫面顯示前 N 檔
DAYTRADE_CLOSE_CANDIDATES = 240  # 收盤後抓券商分點的候選股數 (強勢/爆量/高當沖比)
# 隔日沖券商分點 (常見名單，依網路公開整理；可自行增減)。比對時會去掉「-」「證券」等字再做子字串比對。
OVERNIGHT_BROKERS = ["凱基台北", "凱基松山", "凱基虎尾", "元大土城永寧", "富邦建國", "富邦嘉義", "富邦虎尾", "群益金鼎大安",
                     "統一士林", "國票敦北法人", "國泰敦南", "美林", "摩根大通", "康和板橋"]
