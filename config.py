"""
Configuration settings for the Expense Dashboard
"""

# Google Sheets Configuration
SHEET_ID = "16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ"
WORKSHEET_GID = 453361449  # Plain text sheet GID as per latest architecture

# CSV Fallback URL (for when API is not available)
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={WORKSHEET_GID}"

# Authentication
FAMILY_PIN = "0727"  # Simple family PIN protection

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

# Type_1 Options (Daily vs Travel)
TYPE_1_OPTIONS = ["📅 日常", "✈️ 旅遊"]

# Quick Favorites for mobile-first entry (matching your form categories)
QUICK_FAVORITES = {
    "☕ 咖啡": {"type_1": "📅 日常", "category_type": "dining", "amount": 150},
    "🚗 停車": {"type_1": "📅 日常", "category_type": "transportation", "amount": 100},
    "⛽ 加油": {"type_1": "📅 日常", "category_type": "transportation", "amount": 1200},
    "🍜 午餐": {"type_1": "📅 日常", "category_type": "dining", "amount": 200},
    "🛒 生活用品": {"type_1": "📅 日常", "category_type": "household", "amount": 300},
    "🚌 公車": {"type_1": "📅 日常", "category_type": "transportation", "amount": 30},
    "🥤 飲料": {"type_1": "📅 日常", "category_type": "dining", "amount": 80},
    "🎬 娛樂": {"type_1": "📅 日常", "category_type": "entertainment", "amount": 500}
}

# Category Options (Type_2 from your Google Form - 17 categories)
CATEGORIES = [
    "dining",          # 飲食
    "transportation",  # 交通
    "baby",           # 嬰兒用品
    "household",      # 家用品
    "insurance",      # 保險
    "medical",        # 醫療
    "education",      # 教育
    "accommodation",  # 住宿
    "tickets",        # 票券
    "clothing",       # 衣飾
    "entertainment",  # 娛樂
    "beauty",         # 美容
    "taxes",          # 稅務
    "communication",  # 通訊
    "housing",        # 房屋
    "gifts",          # 禮品
    "pets"            # 寵物
]

# Category Display Names (for UI)
CATEGORY_DISPLAY = {
    "dining": "🍽️ 飲食",
    "transportation": "🚗 交通",
    "baby": "👶 嬰兒用品",
    "household": "🏠 家用品",
    "insurance": "🛡️ 保險",
    "medical": "💊 醫療",
    "education": "📚 教育",
    "accommodation": "🏨 住宿",
    "tickets": "🎫 票券",
    "clothing": "👕 衣飾",
    "entertainment": "🎯 娛樂",
    "beauty": "💄 美容",
    "taxes": "💰 稅務",
    "communication": "📱 通訊",
    "housing": "🏘️ 房屋",
    "gifts": "🎁 禮品",
    "pets": "🐕 寵物"
}

# Account Options (Family Members - matching your Google Form)
ACCOUNTS = ["菇菇", "過兒"]

# Location Hierarchy (matching your Google Form exactly)
LOCATIONS_MAP = {
    "台灣": [
        "基隆市", "台北市", "新北市", "桃園市", "新竹市", "新竹縣",
        "苗栗縣", "台中市", "彰化縣", "南投縣", "雲林縣", "嘉義市",
        "嘉義縣", "台南市", "高雄市", "屏東縣", "宜蘭縣", "花蓮縣",
        "台東縣", "澎湖縣"
    ],
    "日本": ["九州", "沖繩"],
    "澳洲": ["雪梨", "墨爾本"],
    "加拿大": ["溫哥華"],
    "韓國": ["首爾"]
}

# Default Values
DEFAULT_TYPE_1 = "📅 Daily"
DEFAULT_COUNTRY = "台灣"
DEFAULT_LOCATION = "台南市"
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