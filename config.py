"""
Configuration settings for the Expense Dashboard
"""

# Google Sheets Configuration
SHEET_ID = "your-google-sheet-id-here"
WORKSHEET_GID = 453361449  # Plain text sheet GID as per latest architecture

# CSV Fallback URL (for when API is not available)
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={WORKSHEET_GID}"

# Authentication
FAMILY_PIN = "0727"  # Simple family PIN protection

# Column Mapping (Chinese to English for internal processing)
COLUMN_MAPPING = {
    '日期': 'date',
    '類型_1': 'category_emoji',
    '類型_2': 'category_type',
    '金額': 'amount',
    '帳戶': 'account',
    '名稱': 'description',
    '國家': 'country',
    '地點': 'location',
    '備註': 'notes',
    '合併地點': 'combined_location'  # As per recent updates
}

# Quick Favorites for mobile-first entry
QUICK_FAVORITES = {
    "☕ 咖啡": {"category_emoji": "🍽️", "category_type": "飲食", "amount": 150},
    "🚗 停車": {"category_emoji": "🚗", "category_type": "交通", "amount": 100},
    "⛽ 加油": {"category_emoji": "🚗", "category_type": "交通", "amount": 1200},
    "🍜 午餐": {"category_emoji": "🍽️", "category_type": "飲食", "amount": 200},
    "🛒 生活用品": {"category_emoji": "🛍️", "category_type": "日用品", "amount": 300},
    "🚌 公車": {"category_emoji": "🚗", "category_type": "交通", "amount": 30},
    "🥤 飲料": {"category_emoji": "🍽️", "category_type": "飲食", "amount": 80},
    "🎬 娛樂": {"category_emoji": "🎯", "category_type": "娛樂", "amount": 500}
}

# Category Options
CATEGORIES = {
    "🍽️ 飲食": ["早餐", "午餐", "晚餐", "飲料", "零食", "咖啡"],
    "🚗 交通": ["加油", "停車", "公車", "計程車", "高鐵", "機票"],
    "🛍️ 購物": ["衣服", "日用品", "電子產品", "書籍", "禮物"],
    "🎯 娛樂": ["電影", "遊戲", "旅遊", "運動", "音樂"],
    "🏠 居住": ["房租", "水電", "網路", "維修", "清潔"],
    "💊 醫療": ["看診", "藥品", "檢查", "保險"],
    "📚 教育": ["學費", "書籍", "課程", "文具"],
    "💰 其他": ["轉帳", "提款", "匯費", "雜項"]
}

# Account Options (Family Members)
ACCOUNTS = ["YT", "Liu", "共同", "其他"]

# Location Hierarchy
LOCATIONS_MAP = {
    "台灣": ["高雄", "臺南", "台中", "台北", "桃園", "新竹", "嘉義", "屏東", "其他"],
    "日本": ["九州", "沖繩", "東京", "大阪", "京都", "其他"],
    "澳洲": ["墨爾本", "雪梨", "布里斯本", "伯斯", "其他"],
    "美國": ["加州", "紐約", "德州", "佛羅里達", "其他"],
    "其他": ["線上", "不明", "其他"]
}

# Default Values
DEFAULT_COUNTRY = "台灣"
DEFAULT_LOCATION = "臺南"
DEFAULT_ACCOUNT = "YT"

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