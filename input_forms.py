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
            account = st.selectbox(
                "帳戶 👤",
                options=ACCOUNTS,
                index=0,  # Default to first account
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

        # Amount input (suggestions removed to fix form issues)
        amount = st.number_input(
            "金額 💰",
            min_value=0,
            step=10,
            value=suggestions.get("avg_amount", 0),
            help="支出金額"
        )

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
            # Validate required fields
            if not description.strip():
                st.error("請填寫支出描述")
                return False

            if amount <= 0:
                st.error("請填寫有效的金額")
                return False

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
            success = api.add_expense(expense_data)

            if success:
                st.success(f"✅ 成功新增支出: {description} - NT${amount:,.0f}")
                return True
            else:
                st.error("❌ 新增失敗，請稍後再試")
                return False

    return False


def edit_expense_form(df: pd.DataFrame) -> bool:
    """
    Form for editing existing expenses
    """
    st.subheader("✏️ 編輯支出")

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

    # Display recent expenses for selection
    st.caption("選擇要編輯的支出:")

    # Create a selection table
    display_df = df_sorted.head(20).copy()  # Show last 20 expenses

    if 'date' in display_df.columns:
        display_df['日期'] = display_df['date'].dt.strftime('%m/%d')
    display_df['描述'] = display_df.get('description', '')
    display_df['金額'] = display_df.get('amount', 0).apply(lambda x: f"NT${x:,.0f}")
    display_df['帳戶'] = display_df.get('account', '')

    # Create selection interface
    selected_cols = ['日期', '描述', '金額', '帳戶']
    selection_df = display_df[selected_cols].copy()

    # Use dataframe for selection
    event = st.dataframe(
        selection_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    if event.selection and len(event.selection.rows) > 0:
        selected_display_idx = event.selection.rows[0]  # Index in the displayed table
        selected_row = df_sorted.iloc[selected_display_idx]  # Get the full row data

        # Get the ORIGINAL index for updating the correct row in Google Sheets
        original_row_index = selected_row['original_index']

        # Debug info
        st.caption(f"🔍 Debug: 選擇顯示行 {selected_display_idx}, 原始資料行 {original_row_index}")

        st.divider()
        st.subheader("編輯所選支出")

        # Show current values and allow editing
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
                        st.success("✅ 支出已更新")
                        return True
                    else:
                        st.error("❌ 更新失敗")

                elif action == "刪除支出":
                    # Direct deletion - use ORIGINAL row index, not display index
                    success = api.delete_expense(original_row_index)
                    if success:
                        st.success("✅ 支出已刪除")
                        return True
                    else:
                        st.error("❌ 刪除失敗")

    return False