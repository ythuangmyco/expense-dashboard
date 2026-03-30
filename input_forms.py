"""
Mobile-First Expense Input Forms
Enhanced UX for quick expense entry
"""

import streamlit as st
from datetime import datetime, date
from sheets_api import get_sheets_api
import pandas as pd
import re
from PIL import Image

# Categories and locations from your original Google Form
DAILY_CATEGORIES = {
    "🍽️ 飲食": "🍽️ 飲食",
    "🚗 交通": "🚗 交通",
    "👶 寶寶": "👶 寶寶",
    "🧴 日用": "🧴 日用",
    "🏥 醫療": "🏥 醫療",
    "📚 教育": "📚 教育",
    "🏠 住宿": "🏠 住宿",
    "🎫 門票": "🎫 門票",
    "👕 服飾": "👕 服飾",
    "🎮 娛樂": "🎮 娛樂",
    "💄 美容": "💄 美容",
    "💰 稅務": "💰 稅務",
    "📞 通訊": "📞 通訊",
    "🏡 房屋": "🏡 房屋",
    "🎁 禮物": "🎁 禮物",
    "🐕 寵物": "🐕 寵物",
    "🚗 保險": "🚗 保險"
}

TRAVEL_CATEGORIES = {
    "✈️ 交通": "✈️ 交通",
    "🍽️ 飲食": "🍽️ 飲食",
    "🏨 住宿": "🏨 住宿",
    "🎫 門票": "🎫 門票",
    "🛍️ 購物": "🛍️ 購物",
    "🎮 娛樂": "🎮 娛樂"
}

COUNTRIES = {
    "台灣": "台灣",
    "日本": "日本",
    "澳洲": "澳洲",
    "加拿大": "加拿大",
    "韓國": "韓國"
}

TAIWAN_LOCATIONS = [
    "高雄", "臺南", "台中", "台北", "新北", "桃園", "新竹", "苗栗",
    "彰化", "南投", "雲林", "嘉義", "屏東", "宜蘭", "花蓮", "台東",
    "澎湖", "金門", "連江", "基隆"
]

JAPAN_LOCATIONS = ["九州", "沖繩"]
AUSTRALIA_LOCATIONS = ["墨爾本", "雪梨"]
CANADA_LOCATIONS = ["溫哥華", "卡加利", "愛德蒙頓"]
KOREA_LOCATIONS = ["釜山"]

ACCOUNTS = ["菇菇", "過兒"]

def extract_amount_from_image(filename):
    """Try to extract amount from image filename or basic analysis"""
    try:
        # Look for numbers in filename that might be amounts
        numbers = re.findall(r'\d+', filename)
        if numbers:
            # Look for reasonable amounts (between 10 and 10000)
            for num in numbers:
                amount = int(num)
                if 10 <= amount <= 10000:
                    return amount
        return None
    except:
        return None

def get_smart_suggestions(df, category_type):
    """Generate smart suggestions based on historical data"""
    if df.empty:
        return {}

    # Filter by category type
    category_df = df[df['category_type'] == category_type]

    suggestions = {}

    # Most common descriptions for this category
    descriptions = category_df['description'].value_counts().head(5)
    suggestions['descriptions'] = descriptions.index.tolist()

    # Most common amounts for this category
    amounts = category_df['amount'].value_counts().head(3)
    suggestions['amounts'] = amounts.index.tolist()

    # Average amount
    suggestions['avg_amount'] = int(category_df['amount'].mean()) if not category_df.empty else 0

    # Most common locations
    locations = category_df['location'].value_counts().head(3)
    suggestions['locations'] = locations.index.tolist()

    return suggestions

def show_smart_suggestions(df, category_type):
    """Display smart suggestions based on user patterns"""
    suggestions = get_smart_suggestions(df, category_type)

    if suggestions:
        with st.expander("💡 智慧建議 (基於您的記錄)", expanded=True):
            col1, col2 = st.columns(2)

            with col1:
                if suggestions.get('descriptions'):
                    st.write("**常見項目:**")
                    for i, desc in enumerate(suggestions['descriptions'][:3]):
                        if st.button(f"📝 {desc}", key=f"suggest_desc_{desc}_{category_type}_{i}"):
                            st.session_state['suggested_description'] = desc
                            st.session_state['form_description'] = desc
                            st.rerun()

            with col2:
                if suggestions.get('amounts'):
                    st.write("**常見金額:**")
                    for i, amount in enumerate(suggestions['amounts'][:3]):
                        if st.button(f"💰 NT${int(amount)}", key=f"suggest_amt_{amount}_{category_type}_{i}"):
                            st.session_state['suggested_amount'] = int(amount)
                            st.session_state['form_amount'] = int(amount)
                            st.rerun()

            # Show average
            if suggestions.get('avg_amount'):
                st.info(f"📊 此類別平均金額: NT${suggestions['avg_amount']}")

def get_auto_complete_options(df, field_name):
    """Get auto-complete options for input fields"""
    if df.empty:
        return []

    if field_name == 'description':
        return df['description'].value_counts().head(20).index.tolist()
    elif field_name == 'location':
        return df['location'].value_counts().head(10).index.tolist()

    return []

# Quick entry favorites (common expenses)
QUICK_FAVORITES = {
    "☕ 咖啡": {"category_emoji": "📅 日常", "category_type": "🍽️ 飲食", "amount": 150, "description": "咖啡"},
    "🚗 停車": {"category_emoji": "📅 日常", "category_type": "🚗 交通", "amount": 100, "description": "停車費"},
    "⛽ 加油": {"category_emoji": "📅 日常", "category_type": "🚗 交通", "amount": 1200, "description": "加油"},
    "🍱 午餐": {"category_emoji": "📅 日常", "category_type": "🍽️ 飲食", "amount": 300, "description": "午餐"},
    "🥤 飲料": {"category_emoji": "📅 日常", "category_type": "🍽️ 飲食", "amount": 50, "description": "飲料"},
    "🚇 捷運": {"category_emoji": "📅 日常", "category_type": "🚗 交通", "amount": 40, "description": "捷運"},
    "🍼 奶粉": {"category_emoji": "📅 日常", "category_type": "👶 寶寶", "amount": 500, "description": "奶粉"},
    "🛒 買菜": {"category_emoji": "📅 日常", "category_type": "🧴 日用", "amount": 200, "description": "買菜"}
}

def get_locations_for_country(country):
    """Get location list based on selected country"""
    locations_map = {
        "台灣": TAIWAN_LOCATIONS,
        "日本": JAPAN_LOCATIONS,
        "澳洲": AUSTRALIA_LOCATIONS,
        "加拿大": CANADA_LOCATIONS,
        "韓國": KOREA_LOCATIONS
    }
    return locations_map.get(country, [])

def quick_entry_section():
    """Quick entry buttons for common expenses"""
    st.subheader("⚡ 快速記帳")

    # Create a grid of quick entry buttons
    cols = st.columns(4)

    for i, (name, data) in enumerate(QUICK_FAVORITES.items()):
        with cols[i % 4]:
            if st.button(name, key=f"quick_{i}", use_container_width=True):
                return create_quick_expense(data)

    return None

def create_quick_expense(favorite_data):
    """Create expense from quick entry data"""
    # Set default values in session state
    st.session_state.update({
        'quick_category_emoji': favorite_data['category_emoji'],
        'quick_category_type': favorite_data['category_type'],
        'quick_amount': favorite_data['amount'],
        'quick_description': favorite_data['description'],
        'quick_entry_active': True
    })
    return True

def expense_input_form(df=None):
    """Main expense input form with mobile-first design"""

    st.subheader("📝 新增支出")

    # Check if this is a quick entry
    quick_entry = st.session_state.get('quick_entry_active', False)

    # Show smart suggestions OUTSIDE the form (so buttons work)
    if df is not None and not df.empty:
        # Get category for suggestions
        preview_category = st.session_state.get('form_category_detail', '🍽️ 飲食')
        show_smart_suggestions(df, preview_category)

    st.divider()

    # Country/Location selection OUTSIDE form (so it can refresh properly)
    st.subheader("🌍 地點選擇")
    col1, col2 = st.columns(2)

    with col1:
        selected_country = st.selectbox(
            "國家",
            list(COUNTRIES.keys()),
            index=0,  # Taiwan is first, so index=0
            key="expense_country"
        )

    with col2:
        locations = get_locations_for_country(selected_country)
        if locations:
            # Default to Tainan if Taiwan is selected
            default_index = 0
            if selected_country == "台灣" and "臺南" in locations:
                default_index = locations.index("臺南")

            selected_location = st.selectbox(
                "地點",
                locations,
                index=default_index,
                key="expense_location"
            )
        else:
            selected_location = st.text_input(
                "地點",
                placeholder=f"請輸入{selected_country}的地點",
                key="expense_location_text"
            )

    st.divider()

    with st.form("expense_form", clear_on_submit=True):
        # Date input
        expense_date = st.date_input(
            "日期",
            value=date.today(),
            key="form_date"
        )

        # Category selection
        col1, col2 = st.columns(2)

        with col1:
            category_type = st.selectbox(
                "類型",
                ["📅 日常", "✈️ 旅遊"],
                index=0,
                key="form_category_type"
            )

        with col2:
            # Select appropriate category list
            if category_type == "📅 日常":
                categories = DAILY_CATEGORIES
            else:
                categories = TRAVEL_CATEGORIES

            category_detail = st.selectbox(
                "分類",
                list(categories.values()),
                index=0 if not quick_entry else list(categories.values()).index(
                    st.session_state.get('quick_category_type', list(categories.values())[0])
                ),
                key="form_category_detail"
            )

        # Smart suggestions are now shown above the form

        # Amount and account
        col1, col2 = st.columns(2)

        with col1:
            # Use suggested amount if available
            suggested_amount = st.session_state.get('suggested_amount', 0)
            default_amount = 0
            if quick_entry:
                default_amount = st.session_state.get('quick_amount', 0)
            elif suggested_amount:
                default_amount = suggested_amount
                # Clear suggestion after use
                st.session_state.pop('suggested_amount', None)

            amount = st.number_input(
                "金額 (NT$)",
                min_value=0.0,
                value=float(default_amount) if default_amount else 0.0,
                step=1.0,
                key="form_amount"
            )

        with col2:
            account = st.selectbox(
                "帳戶",
                ACCOUNTS,
                index=0,
                key="form_account"
            )

        # Description
        suggested_description = st.session_state.get('suggested_description', '')
        default_description = ''
        if quick_entry:
            default_description = st.session_state.get('quick_description', '')
        elif suggested_description:
            default_description = suggested_description
            # Clear suggestion after use
            st.session_state.pop('suggested_description', None)

        description = st.text_input(
            "項目名稱",
            value=default_description,
            placeholder="例：午餐、停車費、咖啡...",
            key="form_description"
        )

        # Location values are taken from outside the form
        country = selected_country  # Use the country selected outside form
        location = selected_location  # Use the location selected outside form

        # Show selected location in form for reference
        st.info(f"📍 將記錄到: {country} - {location}")

        # Notes
        notes = st.text_area(
            "備註",
            placeholder="其他說明...",
            height=80,
            key="form_notes"
        )

        # Receipt photo upload
        st.divider()

        with st.expander("📸 上傳收據照片 (選填)"):
            uploaded_file = st.file_uploader(
                "選擇收據照片",
                type=['png', 'jpg', 'jpeg'],
                help="可上傳收據照片作為記錄",
                key="form_receipt"
            )

            if uploaded_file is not None:
                # Display image
                image = Image.open(uploaded_file)
                st.image(image, caption="收據照片", width=300)

                # Try to extract amount from filename or basic analysis
                extracted_amount = extract_amount_from_image(uploaded_file.name)
                if extracted_amount and not st.session_state.get('form_amount', 0):
                    st.info(f"💡 偵測到可能金額: NT${extracted_amount}")
                    if st.button("套用偵測金額"):
                        st.session_state['form_amount'] = extracted_amount
                        st.rerun()

        # Submit button
        submitted = st.form_submit_button(
            "💰 記錄支出",
            use_container_width=True,
            type="primary"
        )

        if submitted:
            # Clear quick entry flag
            st.session_state['quick_entry_active'] = False

            # Validate input
            if amount <= 0:
                st.error("請輸入有效的金額")
                return False

            if not description.strip():
                st.error("請輸入項目名稱")
                return False

            # Prepare expense data
            expense_data = {
                'date': expense_date.strftime('%m/%d/%Y'),
                'category_emoji': category_type,
                'category_type': category_detail,
                'amount': amount,
                'account': account,
                'description': description.strip(),
                'country': country,
                'location': location if locations else location,
                'notes': notes.strip()
            }

            # Try to add to Google Sheets
            if st.session_state.get('api_available', False):
                sheets_api = get_sheets_api()
                if sheets_api.add_expense(expense_data):
                    st.success(f"✅ 成功記錄 NT${amount} - {description}")
                    st.balloons()
                    return True
                else:
                    st.error("❌ 記錄失敗，請檢查網路連線")
                    return False
            else:
                st.warning("⚠️ 請先設定 Google Sheets API 以啟用記錄功能")
                st.info("目前為僅讀取模式。請參考 GOOGLE_API_SETUP.md 設定說明")
                return False

    return False

def edit_expense_form(df):
    """Form for editing existing expenses"""

    if df.empty:
        st.info("沒有可編輯的記錄")
        return

    st.subheader("✏️ 編輯支出")

    # Select expense to edit
    recent_expenses = df.head(20).copy()
    recent_expenses['display'] = (
        recent_expenses['date'].dt.strftime('%m/%d') + " - " +
        recent_expenses['description'] + " (NT$" +
        recent_expenses['amount'].astype(str) + ")"
    )

    selected_display = st.selectbox(
        "選擇要編輯的記錄",
        recent_expenses['display'].tolist(),
        key="edit_selector"
    )

    if selected_display:
        # Get selected expense
        selected_idx = recent_expenses[recent_expenses['display'] == selected_display].index[0]
        expense = recent_expenses.loc[selected_idx]

        # Show edit form
        with st.form("edit_expense_form"):
            st.write(f"**編輯記錄:** {expense['description']}")

            # Edit fields
            col1, col2 = st.columns(2)

            with col1:
                new_amount = st.number_input(
                    "金額",
                    value=float(expense['amount']),
                    min_value=0.0,
                    step=1.0
                )

            with col2:
                new_account = st.selectbox(
                    "帳戶",
                    ACCOUNTS,
                    index=ACCOUNTS.index(expense['account'])
                )

            new_description = st.text_input(
                "項目名稱",
                value=expense['description']
            )

            new_notes = st.text_area(
                "備註",
                value=expense.get('notes', ''),
                height=60
            )

            # Action buttons
            col1, col2 = st.columns(2)

            with col1:
                update_submitted = st.form_submit_button(
                    "💾 更新",
                    use_container_width=True
                )

            with col2:
                delete_submitted = st.form_submit_button(
                    "🗑️ 刪除",
                    use_container_width=True
                )

            if update_submitted:
                # Update expense
                updated_data = {
                    'date': expense['date'].strftime('%m/%d/%Y'),
                    'category_emoji': expense['category_emoji'],
                    'category_type': expense['category_type'],
                    'amount': new_amount,
                    'account': new_account,
                    'description': new_description,
                    'country': expense['country'],
                    'location': expense['location'],
                    'notes': new_notes
                }

                if st.session_state.get('api_available', False):
                    sheets_api = get_sheets_api()
                    if sheets_api.update_expense(selected_idx, updated_data):
                        st.success("✅ 記錄已更新")
                        st.rerun()
                    else:
                        st.error("❌ 更新失敗")
                else:
                    st.warning("⚠️ 需要 API 權限才能編輯")

            elif delete_submitted:
                if st.session_state.get('api_available', False):
                    sheets_api = get_sheets_api()
                    if sheets_api.delete_expense(selected_idx):
                        st.success("✅ 記錄已刪除")
                        st.rerun()
                    else:
                        st.error("❌ 刪除失敗")
                else:
                    st.warning("⚠️ 需要 API 權限才能刪除")