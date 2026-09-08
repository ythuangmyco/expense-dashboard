"""
Configuration settings for the Expense Dashboard
"""

# Google Sheets Configuration
SHEET_ID = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
WORKSHEET_GID = 453361449  # Plain text sheet GID as per latest architecture

# CSV Fallback URL (for when API is not available)
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={WORKSHEET_GID}"

# Authentication
FAMILY_PIN = "A127dw@ekCbT"  # Family password protection
ALLOWED_USERS = ["菇菇", "過兒"]  # Authorized family members

# Note: Authentication is now ENABLED
# Users must select their name (菇菇 or 過兒) + enter family password to access the app
# To disable authentication:
# 1. Go to auth.py
# 2. Change DISABLE_AUTH = False to DISABLE_AUTH = True

# Column Mapping (matching your Google Form structure)
# Handle both proper Chinese and UTF-8 encoded versions
COLUMN_MAPPING = {
    # Proper Chinese characters
    '日期': 'date',
    '類型_1': 'type_1',          # Daily vs Travel
    '類型_2': 'category_type',   # Specific category (dining, transportation, etc.)
    '金額': 'amount',
    '帳戶': 'account',           # 菇菇 or 過兒
    '名稱': 'description',
    '國家': 'country',
    '地點': 'location',
    '備註': 'notes',

    # Optional foreign-currency columns (added 2026-09; blank = TWD-native row)
    '幣別': 'currency',
    '原幣金額': 'orig_amount',
    '匯率': 'fx_rate',

    # Additional possible amount column names
    'Amount': 'amount',
    'amount': 'amount',
    'AMOUNT': 'amount',
    '費用': 'amount',
    '金钱': 'amount',
    'Cost': 'amount',
    'Money': 'amount',
    '支出': 'amount',

    # UTF-8 encoded versions (fallback for CSV encoding issues)
    'æ\x97¥æ\x9c\x9f': 'date',
    'é¡\x9eå\x9e\x8b_1': 'type_1',
    'é¡\x9eå\x9e\x8b_2': 'category_type',
    'é\x87\x91é¡\x8d': 'amount',
    'å¸³æ\x88¶': 'account',
    'å\x90\x8dç¨±': 'description',
    'å\x9c\x8bå®¶': 'country',
    'å\x9c°é»\x9e': 'location',
    'å\x82\x99è¨»': 'notes'
}

# Type_1 Options (Daily vs Travel) - EXACT match to Google Form
TYPE_1_OPTIONS = ["📅 日常", "✈️ 旅行"]

# Quick favorites removed as requested

# Category Options (Type_2) - EXACT match to Google Form
CATEGORIES = [
    "🍽️ 飲食",
    "🚗 交通",
    "👶 寶寶",
    "🧴 日用",
    "🛡️ 保險",
    "🏥 醫療",
    "📚 教育",
    "🏨 住宿",
    "🎫 門票雜支",
    "👗 服飾",
    "🎮 娛樂",
    "💄 美容",
    "📄 稅金",
    "📱 通信",
    "🏠 住房物業",
    "🎁 禮物",
    "🐾 寵物"
]

# Account Options (Family Members - matching your Google Form)
ACCOUNTS = ["菇菇", "過兒"]

# Location Hierarchy (matching your Google Form exactly)
LOCATIONS_MAP = {
    # Spelling follows the vocabulary already used in the sheet
    # (no 市/縣 suffix, 臺 not 台): 臺南, 高雄, 新竹, 屏東, 南投, 苗栗, ...
    "台灣": [
        "基隆", "臺北", "新北", "桃園", "新竹", "苗栗", "臺中", "彰化",
        "南投", "雲林", "嘉義", "臺南", "高雄", "屏東", "宜蘭", "花蓮",
        "臺東", "澎湖"
    ],
    "日本": ["九州", "沖繩"],
    "澳洲": ["雪梨", "墨爾本"],
    "加拿大": ["溫哥華"],
    "韓國": ["首爾"],
    "新加坡": ["新加坡"],
    "馬來西亞": ["吉隆坡"]
}

# Default Values
DEFAULT_TYPE_1 = "📅 日常"
DEFAULT_COUNTRY = "台灣"
DEFAULT_LOCATION = "臺南"
DEFAULT_ACCOUNT = "菇菇"

# UI Configuration
PAGE_CONFIG = {
    "page_title": "💰 HuangLiuHome Expense",
    "page_icon": "📊",
    "layout": "wide",
    "initial_sidebar_state": "collapsed"  # Mobile-first
}

# Chart Colors (for consistent theming)
COLORS = {
    "primary": "#FF6B6B",
    "secondary": "#4ECDC4",
    "accent": "#45B7D1",
    "background": "#F8F9FA",
    "text": "#2C3E50"
}

# ---------------------------------------------------------------------------
# Foreign-currency conversion (外幣換算). See PLAN_fx_and_overview.md §2.
# ---------------------------------------------------------------------------
from decimal import Decimal  # noqa: E402

# Optional sheet headers (written by name, after the 9 required ones)
OPTIONAL_HEADERS = ["幣別", "原幣金額", "匯率"]

# Default currency per 國家 (use .get(country, "TWD"))
COUNTRY_CURRENCY = {
    "台灣": "TWD", "日本": "JPY", "澳洲": "AUD", "加拿大": "CAD",
    "韓國": "KRW", "新加坡": "SGD", "馬來西亞": "MYR",
}
CURRENCY_OPTIONS = ["TWD", "SGD", "MYR", "JPY", "KRW", "AUD", "CAD", "USD", "EUR"]
# code -> (decimals shown/stored for the original amount, number_input step)
CURRENCY_META = {
    "TWD": (0, 1.0), "JPY": (0, 1.0), "KRW": (0, 1.0),
    "SGD": (2, 0.01), "MYR": (2, 0.01), "AUD": (2, 0.01), "CAD": (2, 0.01),
    "USD": (2, 0.01), "EUR": (2, 0.01),
}
RATE_DECIMALS = 6                 # 匯率 stored with 6 dp for every currency
CARD_FX_FEE = Decimal("0.015")    # optional 信用卡結匯 surcharge
FX_TIMEOUT_S = 3                  # per-endpoint HTTP timeout
FX_TTL_H = 12                     # a fetched quote is reused for this long
FX_NEG_CACHE_MIN = 10             # after a failed chain, do not retry for this long
FX_ENDPOINTS = {
    "frankfurter": "https://api.frankfurter.dev/v2/rates",
    "erapi": "https://open.er-api.com/v6/latest/{ccy}",
    "fawaz_cdn": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date}/v1/currencies/{ccy}.min.json",
    "fawaz_pages": "https://{date}.currency-api.pages.dev/v1/currencies/{ccy}.min.json",
}
# Last-resort static rates: TWD per 1 unit. Refresh occasionally (see DEPLOYMENT.md).
FX_FALLBACK_DATE = "2026-09-08"
FX_FALLBACK_RATES = {
    "USD": 31.54, "SGD": 24.91, "MYR": 7.79, "JPY": 0.2035, "KRW": 0.02345,
    "AUD": 22.77, "CAD": 22.84, "EUR": 36.66,
}

# ---------------------------------------------------------------------------
# 總覽 (overview) settings. See PLAN_fx_and_overview.md §3.
# ---------------------------------------------------------------------------
OVERVIEW_PERIODS = ["今天", "本週", "本月", "本年", "更多…"]
OVERVIEW_MORE_PERIODS = ["上月", "最近7天", "最近30天", "全部"]
COMPARISON_LABEL = {
    "今天": "昨天", "本週": "上週同期", "本月": "上月同期", "上月": "前一個月",
    "本年": "去年同期", "最近7天": "前 7 天", "最近30天": "前 30 天",
    "自訂範圍": "前一段同長期間", "全部": None, "旅行": None,
}
# Display-time only: raw sheet values are never rewritten
CATEGORY_ALIASES = {"📱通信": "📱 通信"}
COUNTRY_FLAG = {
    "台灣": "🇹🇼", "日本": "🇯🇵", "澳洲": "🇦🇺", "加拿大": "🇨🇦", "韓國": "🇰🇷",
    "新加坡": "🇸🇬", "馬來西亞": "🇲🇾",
}
TRIP_GAP_DAYS = 3                 # split trips in the same country on gaps longer than this
TRIP_PREBOOK_WINDOW_DAYS = 180    # 旅行 rows with 國家=台灣 attach to the next trip within this window
TRIP_ACTIVE_GRACE_DAYS = 3        # a trip whose last row is within this many days counts as active
