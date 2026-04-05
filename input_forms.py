"""
Mobile-first input forms for quick expense entry
Focus on speed and ease of use on mobile devices
"""

import streamlit as st
import pandas as pd
from datetime import datetime, date
from typing import Dict, List, Optional
from config import (
    TYPE_1_OPTIONS, CATEGORIES, ACCOUNTS, LOCATIONS_MAP,
    DEFAULT_TYPE_1, DEFAULT_COUNTRY, DEFAULT_LOCATION, DEFAULT_ACCOUNT
)
from sheets_api import get_sheets_api
from auth import get_current_user


# Quick entry section removed as requested


def smart_suggestions(df: pd.DataFrame, category_type: str = None) -> Dict:
    """
    Generate smart suggestions based on user patterns
    """
    suggestions = {
        "descriptions": [],
        "amounts": [],
        "avg_amount": 0,
        "common_accounts": [],
        "common_locations": []
    }

    if df.empty:
        return suggestions

    try:
        # Filter by category if provided
        filtered_df = df
        if category_type and 'category_type' in df.columns:
            filtered_df = df[df['category_type'] == category_type]

        if not filtered_df.empty:
            # Most common descriptions
            if 'description' in filtered_df.columns:
                descriptions = filtered_df['description'].value_counts().head(5)
                suggestions["descriptions"] = descriptions.index.tolist()

            # Most common amounts
            if 'amount' in filtered_df.columns:
                # Ensure amounts are numeric
                numeric_amounts = pd.to_numeric(filtered_df['amount'], errors='coerce').fillna(0)
                amounts = numeric_amounts.value_counts().head(3)
                suggestions["amounts"] = amounts.index.tolist()
                try:
                    suggestions["avg_amount"] = int(numeric_amounts.mean()) if numeric_amounts.mean() > 0 else 0
                except:
                    suggestions["avg_amount"] = 0

            # Most common accounts
            if 'account' in filtered_df.columns:
                accounts = filtered_df['account'].value_counts().head(3)
                suggestions["common_accounts"] = accounts.index.tolist()

            # Most common locations
            if 'location' in filtered_df.columns:
                locations = filtered_df['location'].value_counts().head(3)
                suggestions["common_locations"] = locations.index.tolist()

    except Exception as e:
        st.error(f"智能建議生成錯誤: {str(e)}")

    return suggestions


def calculator_widget():
    """Simple calculator widget for amount input"""
    st.markdown("### 🧮 計算機")

    # Initialize calculator state
    if 'calc_display' not in st.session_state:
        st.session_state.calc_display = "0"
    if 'calc_operator' not in st.session_state:
        st.session_state.calc_operator = ""
    if 'calc_operand' not in st.session_state:
        st.session_state.calc_operand = 0
    if 'calc_waiting_operand' not in st.session_state:
        st.session_state.calc_waiting_operand = False

    # Display current value
    st.markdown(f"""
    <div style="
        background: #f0f2f6;
        padding: 15px;
        border-radius: 5px;
        text-align: right;
        font-size: 24px;
        font-weight: bold;
        margin-bottom: 10px;
        border: 2px solid #e0e0e0;
    ">
        {st.session_state.calc_display}
    </div>
    """, unsafe_allow_html=True)

    # Calculator button functions
    def input_digit(digit):
        if st.session_state.calc_waiting_operand:
            st.session_state.calc_display = str(digit)
            st.session_state.calc_waiting_operand = False
        else:
            if st.session_state.calc_display == "0":
                st.session_state.calc_display = str(digit)
            else:
                st.session_state.calc_display += str(digit)

    def input_operator(operator):
        current_value = float(st.session_state.calc_display)

        if st.session_state.calc_operator and not st.session_state.calc_waiting_operand:
            # Perform calculation if there's a pending operation
            if st.session_state.calc_operator == "+":
                result = st.session_state.calc_operand + current_value
            elif st.session_state.calc_operator == "-":
                result = st.session_state.calc_operand - current_value
            elif st.session_state.calc_operator == "*":
                result = st.session_state.calc_operand * current_value
            elif st.session_state.calc_operator == "/":
                result = st.session_state.calc_operand / current_value if current_value != 0 else 0

            st.session_state.calc_display = str(int(result) if result.is_integer() else round(result, 2))
            st.session_state.calc_operand = result
        else:
            st.session_state.calc_operand = current_value

        st.session_state.calc_operator = operator
        st.session_state.calc_waiting_operand = True

    def calculate():
        if st.session_state.calc_operator and not st.session_state.calc_waiting_operand:
            current_value = float(st.session_state.calc_display)

            if st.session_state.calc_operator == "+":
                result = st.session_state.calc_operand + current_value
            elif st.session_state.calc_operator == "-":
                result = st.session_state.calc_operand - current_value
            elif st.session_state.calc_operator == "*":
                result = st.session_state.calc_operand * current_value
            elif st.session_state.calc_operator == "/":
                result = st.session_state.calc_operand / current_value if current_value != 0 else 0

            st.session_state.calc_display = str(int(result) if result.is_integer() else round(result, 2))
            st.session_state.calc_operator = ""
            st.session_state.calc_waiting_operand = True

    def clear():
        st.session_state.calc_display = "0"
        st.session_state.calc_operator = ""
        st.session_state.calc_operand = 0
        st.session_state.calc_waiting_operand = False

    # Button layout
    col1, col2, col3, col4 = st.columns(4)

    # Row 1: Clear and operators
    with col1:
        if st.button("C", key="calc_clear", use_container_width=True):
            clear()
            st.rerun()
    with col2:
        if st.button("÷", key="calc_div", use_container_width=True):
            input_operator("/")
            st.rerun()
    with col3:
        if st.button("×", key="calc_mult", use_container_width=True):
            input_operator("*")
            st.rerun()
    with col4:
        if st.button("−", key="calc_minus", use_container_width=True):
            input_operator("-")
            st.rerun()

    # Row 2: 7, 8, 9, +
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("7", key="calc_7", use_container_width=True):
            input_digit(7)
            st.rerun()
    with col2:
        if st.button("8", key="calc_8", use_container_width=True):
            input_digit(8)
            st.rerun()
    with col3:
        if st.button("9", key="calc_9", use_container_width=True):
            input_digit(9)
            st.rerun()
    with col4:
        if st.button("＋", key="calc_plus", use_container_width=True):
            input_operator("+")
            st.rerun()

    # Row 3: 4, 5, 6
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("4", key="calc_4", use_container_width=True):
            input_digit(4)
            st.rerun()
    with col2:
        if st.button("5", key="calc_5", use_container_width=True):
            input_digit(5)
            st.rerun()
    with col3:
        if st.button("6", key="calc_6", use_container_width=True):
            input_digit(6)
            st.rerun()
    with col4:
        st.markdown("<div style='height: 38px;'></div>", unsafe_allow_html=True)  # Empty space

    # Row 4: 1, 2, 3, =
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        if st.button("1", key="calc_1", use_container_width=True):
            input_digit(1)
            st.rerun()
    with col2:
        if st.button("2", key="calc_2", use_container_width=True):
            input_digit(2)
            st.rerun()
    with col3:
        if st.button("3", key="calc_3", use_container_width=True):
            input_digit(3)
            st.rerun()
    with col4:
        if st.button("＝", key="calc_equals", use_container_width=True):
            calculate()
            st.rerun()

    # Row 5: 0
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("<div style='height: 38px;'></div>", unsafe_allow_html=True)  # Empty space
    with col2:
        if st.button("0", key="calc_0", use_container_width=True):
            input_digit(0)
            st.rerun()
    with col3:
        st.markdown("<div style='height: 38px;'></div>", unsafe_allow_html=True)  # Empty space
    with col4:
        st.markdown("<div style='height: 38px;'></div>", unsafe_allow_html=True)  # Empty space

    # Use result button
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📋 使用這個結果", key="use_calc_result", use_container_width=True, type="primary"):
            try:
                result = float(st.session_state.calc_display)
                st.session_state.calc_result_to_use = result
                st.success(f"✅ 將使用金額：NT${result:,.0f}")
                return result
            except:
                st.error("❌ 無效的計算結果")
                return None

    with col2:
        if st.button("🗑️ 重置計算機", key="reset_calc", use_container_width=True):
            clear()
            st.rerun()

    return None


def expense_input_form(df: pd.DataFrame) -> bool:
    """
    Main expense input form with smart defaults and mobile optimization
    Returns True if expense was successfully added
    """
    st.subheader("📝 詳細記帳")

    # Check if we can add expenses (API availability)
    api = get_sheets_api()
    status = api.get_status()

    if not status["api_available"]:
        st.warning("⚠️ 目前僅支援查看模式，無法新增支出")
        st.info("請確認 Google Sheets API 設定正確")
        return False

    with st.form("expense_form", clear_on_submit=True):
        # First row: Date and Account
        col1, col2 = st.columns(2)
        with col1:
            expense_date = st.date_input(
                "日期 📅",
                value=date.today(),
                help="支出日期"
            )
        with col2:
            # Get current user and set as default if logged in
            current_user = get_current_user()
            default_index = 0  # Default to "請選擇帳戶..."

            # If current user matches an account, set as default
            if current_user and current_user in ACCOUNTS:
                default_index = ACCOUNTS.index(current_user) + 1  # +1 because of "請選擇帳戶..." at index 0

            account = st.selectbox(
                "帳戶 👤",
                options=["請選擇帳戶..."] + ACCOUNTS,
                index=default_index,
                help="記帳帳戶"
            )

        # Type_1 selection (Daily vs Travel)
        type_1 = st.selectbox(
            "類型 📅",
            options=TYPE_1_OPTIONS,
            index=0,
            help="選擇支出類型"
        )

        # Type_2 selection (Specific category) - Display in Chinese
        category_type = st.selectbox(
            "分類 🏷️",
            options=CATEGORIES,
            help="選擇具體的支出類型"
        )

        # Get smart suggestions for this category
        suggestions = smart_suggestions(df, category_type)

        # Amount input section with calculator
        st.markdown("#### 💰 金額")

        # Check if user wants to use calculator result
        default_amount = None
        if 'calc_result_to_use' in st.session_state:
            default_amount = st.session_state.calc_result_to_use
            del st.session_state.calc_result_to_use  # Clear it after use

        # Calculator toggle
        col1, col2 = st.columns([3, 1])
        with col1:
            amount = st.number_input(
                "輸入金額",
                min_value=0,
                step=10,
                value=default_amount,
                placeholder="請輸入金額...",
                help="支出金額"
            )
        with col2:
            show_calculator = st.button("🧮", help="開啟計算機", use_container_width=True)

        # Show calculator if toggled
        if show_calculator or 'show_calc' in st.session_state:
            if show_calculator:
                st.session_state.show_calc = not st.session_state.get('show_calc', False)

            if st.session_state.get('show_calc', False):
                with st.expander("🧮 計算機", expanded=True):
                    calc_result = calculator_widget()
                    if calc_result is not None:
                        st.session_state.calc_result_to_use = calc_result
                        st.session_state.show_calc = False  # Close calculator
                        st.rerun()

        # Show amount suggestions as text only
        if suggestions["amounts"]:
            try:
                # Safely convert amounts to integers
                safe_amounts = []
                for amt in suggestions['amounts'][:3]:
                    try:
                        safe_amounts.append(f'NT${int(float(amt))}')
                    except:
                        safe_amounts.append(f'NT${amt}')
                st.caption(f"💡 常用金額: {', '.join(safe_amounts)}")
            except Exception as e:
                st.caption("💡 常用金額建議暫時無法顯示")

        # Description input
        description = st.text_input(
            "描述 📝",
            placeholder="支出描述...",
            help="簡單描述這筆支出"
        )

        # Show description suggestions as text only
        if suggestions["descriptions"]:
            st.caption(f"💡 常用描述: {', '.join(suggestions['descriptions'][:3])}")

        # Location selection
        st.caption("📍 地點資訊")
        loc_col1, loc_col2 = st.columns(2)

        with loc_col1:
            country = st.selectbox(
                "國家",
                options=list(LOCATIONS_MAP.keys()),
                index=list(LOCATIONS_MAP.keys()).index(DEFAULT_COUNTRY) if DEFAULT_COUNTRY in LOCATIONS_MAP else 0,
                key="country_select"
            )

        with loc_col2:
            available_locations = LOCATIONS_MAP.get(country, ["其他"])
            default_location_index = 0
            if country == DEFAULT_COUNTRY and DEFAULT_LOCATION in available_locations:
                default_location_index = available_locations.index(DEFAULT_LOCATION)

            location = st.selectbox(
                "地點",
                options=available_locations,
                index=default_location_index,
                key="location_select"
            )

        # Notes (optional)
        notes = st.text_area(
            "備註 (選填) 📄",
            placeholder="其他備註資訊...",
            height=60,
            help="可選的備註資訊"
        )

        # Submit button
        submitted = st.form_submit_button(
            "💾 儲存支出",
            use_container_width=True,
            type="primary"
        )

        if submitted:
            # Prevent duplicate submissions using session state
            submission_key = f"expense_submit_{description}_{amount}_{expense_date}"
            if submission_key in st.session_state:
                st.warning("⚠️ 請勿重複提交相同的支出")
                return False

            # Validate required fields
            if not description.strip():
                st.error("請填寫支出描述")
                return False

            if not amount or amount <= 0:
                st.error("請填寫有效的金額")
                return False

            if account == "請選擇帳戶...":
                st.error("請選擇記帳帳戶")
                return False

            # Mark this submission as in progress
            st.session_state[submission_key] = True

            # Prepare expense data
            expense_data = {
                "date": expense_date.strftime("%Y-%m-%d"),
                "type_1": type_1,
                "category_type": category_type,
                "amount": amount,
                "account": account,
                "description": description.strip(),
                "country": country,
                "location": location,
                "notes": notes.strip()
            }

            # Add to sheet
            import time
            debug_id = f"{time.time():.3f}"
            st.info(f"🔍 DEBUG: Processing submission {debug_id}")

            success = api.add_expense(expense_data)

            if success:
                st.info(f"🔍 DEBUG: Success callback triggered for {debug_id}")
                st.success(f"✅ 成功新增支出: {description} - NT${amount:,.0f}")
                # Clear the submission key after successful submission
                if submission_key in st.session_state:
                    del st.session_state[submission_key]
                return True
            else:
                st.error("❌ 新增失敗，請稍後再試")
                # Clear the submission key after failed submission
                if submission_key in st.session_state:
                    del st.session_state[submission_key]
                return False

    return False


def edit_expense_form(df: pd.DataFrame) -> bool:
    """
    Form for editing existing expenses
    """
    st.subheader("✏️ 編輯支出")

    # Add refresh button
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 重新整理資料"):
            from sheets_api import refresh_data
            refresh_data()
            st.rerun()

    if df.empty:
        st.info("📊 目前沒有支出資料可編輯")
        return False

    # Check API availability
    api = get_sheets_api()
    status = api.get_status()

    if not status["api_available"]:
        st.warning("⚠️ 目前僅支援查看模式，無法編輯支出")
        return False

    # Sort by date (newest first) for easier editing
    df_sorted = df.sort_values('date', ascending=False).reset_index(drop=False)

    # CRITICAL: Store the original index to map back to the correct row
    df_sorted['original_index'] = df_sorted['index']  # This preserves the original row position

    # Create a simple dropdown to select record to edit
    recent_records = df_sorted.head(50)  # Show last 50 expenses for dropdown

    # Create options for dropdown
    record_options = []
    for idx, row in recent_records.iterrows():
        date_str = row['date'].strftime('%m/%d') if pd.notna(row['date']) else 'N/A'
        desc = str(row.get('description', ''))[:20] + ('...' if len(str(row.get('description', ''))) > 20 else '')
        try:
            amount_str = f"NT${float(row.get('amount', 0)):,.0f}"
        except:
            amount_str = "NT$0"

        option_text = f"{date_str} - {desc} - {amount_str}"
        record_options.append((option_text, idx))

    # Dropdown selection with no default
    selected_option = st.selectbox(
        "選擇要編輯的支出記錄：",
        options=["請選擇記錄..."] + [opt[0] for opt in record_options],
        help="選擇一筆要編輯的支出記錄"
    )

    # Get selected record
    if selected_option and selected_option != "請選擇記錄...":
        selected_idx = next(idx for text, idx in record_options if text == selected_option)
        selected_row = recent_records.loc[selected_idx]
        original_row_index = selected_row['original_index']

        st.divider()

        # Show current values and allow editing
        st.subheader(f"編輯支出：{selected_row.get('description', 'N/A')}")

        with st.form("edit_expense_form"):
            col1, col2 = st.columns(2)

            with col1:
                new_date = st.date_input(
                    "日期",
                    value=selected_row['date'].date() if pd.notna(selected_row['date']) else date.today()
                )

            with col2:
                new_account = st.selectbox(
                    "帳戶",
                    options=ACCOUNTS,
                    index=ACCOUNTS.index(selected_row.get('account', ACCOUNTS[0])) if selected_row.get('account') in ACCOUNTS else 0
                )

            # Type_1 selection (Daily vs Travel)
            current_type_1 = selected_row.get('type_1', TYPE_1_OPTIONS[0])
            new_type_1 = st.selectbox(
                "類型",
                options=TYPE_1_OPTIONS,
                index=TYPE_1_OPTIONS.index(current_type_1) if current_type_1 in TYPE_1_OPTIONS else 0
            )

            # Category selection (Type_2)
            current_category_type = selected_row.get('category_type', CATEGORIES[0])
            new_category_type = st.selectbox(
                "分類",
                options=CATEGORIES,
                index=CATEGORIES.index(current_category_type) if current_category_type in CATEGORIES else 0
            )

            # Safe amount conversion - fix type consistency
            try:
                current_amount = float(selected_row.get('amount', 0))
            except (ValueError, TypeError):
                current_amount = 0.0

            new_amount = st.number_input(
                "金額",
                min_value=0.0,
                step=10.0,
                value=current_amount,  # Use consistent float type
                format="%.0f"
            )

            new_description = st.text_input(
                "描述",
                value=selected_row.get('description', '')
            )

            # Action selection and single submit button
            action = st.selectbox(
                "選擇動作",
                ["更新支出", "刪除支出"],
                index=0
            )

            # Single submit button
            submitted = st.form_submit_button(
                f"{'💾 更新' if action == '更新支出' else '🗑️ 刪除'}",
                use_container_width=True,
                type="primary" if action == "更新支出" else "secondary"
            )

            if submitted:
                if action == "更新支出":
                    # Prepare updated data
                    updated_data = {
                        "date": new_date.strftime("%Y-%m-%d"),
                        "type_1": new_type_1,
                        "category_type": new_category_type,
                        "amount": new_amount,
                        "account": new_account,
                        "description": new_description,
                        "country": selected_row.get('country', DEFAULT_COUNTRY),
                        "location": selected_row.get('location', DEFAULT_LOCATION),
                        "notes": selected_row.get('notes', '')
                    }

                    # Update in sheet - use ORIGINAL row index, not display index
                    success = api.update_expense(original_row_index, updated_data)
                    if success:
                        st.success(f"✅ 已更新支出：{new_description} (NT${new_amount:,.0f})")

                        # Auto-refresh the page to show updated data
                        import time
                        time.sleep(1.5)  # Let user see the success message
                        st.rerun()  # Refresh the page
                        return True
                    else:
                        st.error(f"❌ 更新失敗：{new_description}")
                        st.info("💡 請檢查網路連線或重新嘗試")

                elif action == "刪除支出":
                    # Show confirmation with details
                    desc = selected_row.get('description', 'N/A')

                    # Get the original amount (not the form amount for deletion)
                    try:
                        original_amount = float(selected_row.get('amount', 0))
                    except:
                        original_amount = 0

                    date_str = selected_row['date'].strftime('%Y/%m/%d') if pd.notna(selected_row['date']) else 'N/A'

                    # Show what we're about to delete
                    st.info(f"🗑️ 準備刪除: {desc} (NT${original_amount:,.0f}) - {date_str}")

                    # Direct deletion with better row finding
                    success = api.delete_expense(original_row_index, {
                        'description': desc,
                        'amount': original_amount,
                        'date': date_str
                    })
                    if success:
                        st.success(f"✅ 已刪除支出：{desc} (NT${original_amount:,.0f}) - {date_str}")

                        # Auto-refresh the page to show updated data
                        import time
                        time.sleep(1.5)  # Let user see the success message
                        st.rerun()  # Refresh the page
                        return True
                    else:
                        st.error(f"❌ 刪除失敗：{desc}")

                        # Show debugging info
                        with st.expander("🔍 除錯資訊", expanded=False):
                            st.write(f"原始索引: {original_row_index}")
                            st.write(f"描述: {desc}")
                            st.write(f"金額: {original_amount}")
                            st.write(f"日期: {date_str}")
                            st.write("請檢查是否該記錄已被其他人刪除，或重新整理頁面後重試")

    return False