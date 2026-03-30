"""
📊 Personal Expense Dashboard
Real-time visualization of expense tracker data from Google Sheets
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime, timedelta
import numpy as np
from sheets_api import get_sheets_api
from input_forms import quick_entry_section, expense_input_form, edit_expense_form

# Page configuration
st.set_page_config(
    page_title="💰 Expense Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Authentication
def check_password():
    """Returns True if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == "0727":
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.markdown("""
        <div style="display: flex; justify-content: center; align-items: center; height: 50vh;">
            <div style="text-align: center; padding: 2rem; background: white; border-radius: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h1 style="color: #667eea; margin-bottom: 1rem;">🔒 Family Expense Dashboard</h1>
                <p style="color: #666; margin-bottom: 1.5rem;">Enter password to access your expense data</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.text_input("Password", type="password", on_change=password_entered, key="password",
                         placeholder="Enter your 4-digit code")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.markdown("""
        <div style="display: flex; justify-content: center; align-items: center; height: 50vh;">
            <div style="text-align: center; padding: 2rem; background: white; border-radius: 20px; box-shadow: 0 4px 12px rgba(0,0,0,0.1);">
                <h1 style="color: #667eea; margin-bottom: 1rem;">🔒 Family Expense Dashboard</h1>
                <p style="color: #666; margin-bottom: 1.5rem;">Enter password to access your expense data</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            st.text_input("Password", type="password", on_change=password_entered, key="password",
                         placeholder="Enter your 4-digit code")
            st.error("❌ Incorrect password. Please try again.")
        return False
    else:
        # Password correct.
        return True

# Custom CSS for mobile-friendly design
st.markdown("""
<style>
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        margin-bottom: 2rem;
        color: white;
    }

    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
        margin-bottom: 1rem;
    }

    .category-emoji {
        font-size: 2rem;
        margin-right: 0.5rem;
    }

    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .main-header h1 {
            font-size: 1.5rem !important;
        }

        .metric-card {
            padding: 0.5rem;
        }
    }
</style>
""", unsafe_allow_html=True)

# Constants
SHEET_URL = "https://docs.google.com/spreadsheets/d/16JzKmS8Jq9H6NmjrpKkqBqNfnXkC_gfPiMV6Y6qP_kQ/export?format=csv&gid=720407773"

# Cache data loading function
@st.cache_data(ttl=60)  # Cache for 1 minute (shorter for real-time updates)
def load_expense_data():
    """Load expense data from Google Sheets (API or CSV fallback)"""

    # Try Google Sheets API first (for read/write capabilities)
    try:
        sheets_api = get_sheets_api()
        if sheets_api.authenticate():
            df = sheets_api.read_data()
            if not df.empty:
                st.session_state['api_available'] = True
                return df
    except Exception as e:
        st.session_state['api_available'] = False
        # Fall back to CSV if API fails

    # Fallback to CSV export (read-only)
    try:
        st.session_state['api_available'] = False
        df = pd.read_csv(SHEET_URL)

        # Clean column names (remove extra spaces, standardize)
        df.columns = df.columns.str.strip()

        # Rename columns for easier handling
        column_mapping = {
            '日期': 'date',
            '類型_1': 'category_emoji',
            '類型_2': 'category_type',
            '金額': 'amount',
            '帳戶': 'account',
            '名稱': 'description',
            '國家': 'country',
            '地點': 'location',
            '備註': 'notes'
        }

        df = df.rename(columns=column_mapping)

        # Convert date column
        df['date'] = pd.to_datetime(df['date'], errors='coerce')

        # Convert amount to numeric (remove any currency symbols)
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')

        # Remove rows with invalid dates or amounts
        df = df.dropna(subset=['date', 'amount'])

        # Add derived columns
        if not df.empty:
            df['year'] = df['date'].dt.year
            df['month'] = df['date'].dt.month
            df['day_of_week'] = df['date'].dt.day_name()
            df['month_year'] = df['date'].dt.to_period('M').astype(str)

        return df

    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return pd.DataFrame()

def main():
    """Main dashboard function"""

    # Header
    st.markdown("""
    <div class="main-header">
        <h1>📊 Family Expense Dashboard</h1>
        <p>Real-time expense tracking and insights</p>
    </div>
    """, unsafe_allow_html=True)

    # Load data
    with st.spinner("Loading expense data..."):
        df = load_expense_data()

    # Show API status with more details
    api_status = st.session_state.get('api_available', False)
    if api_status:
        st.success("🔗 Google Sheets API 已連接 - 可新增/編輯記錄")
    else:
        # More helpful error message
        if "google_sheets" in st.secrets:
            st.error("🔧 API 認證失敗 - 請檢查 Streamlit Cloud 的 Secrets 設定")
            with st.expander("🛠️ 快速修復"):
                st.markdown("""
                **可能的問題：**
                1. Secrets 格式錯誤
                2. Service Account 權限不足
                3. Google Sheet 未正確分享

                **修復步驟：**
                1. 檢查 Streamlit Cloud → Settings → Secrets
                2. 確認所有必要欄位都存在
                3. 檢查 Google Sheet 是否分享給 service account
                """)
        else:
            st.warning("📖 僅讀取模式 - 查看 GOOGLE_API_SETUP.md 啟用完整功能")

    # Navigation tabs
    tab1, tab2, tab3 = st.tabs(["📊 報表分析", "➕ 新增支出", "✏️ 編輯支出"])

    with tab1:
        # Original dashboard functionality
        if df.empty:
            st.error("No data available. Please check the Google Sheets connection.")
            return
        show_dashboard(df)

    with tab2:
        # Quick entry section
        if api_status:
            if quick_entry_section():
                st.rerun()  # Refresh to show updated quick entry form

            st.divider()

            # Full expense form
            if expense_input_form(df):
                st.rerun()  # Refresh to show new data
        else:
            st.info("🔑 請先設定 Google Sheets API 以啟用記錄功能")
            st.markdown("""
            **設定步驟:**
            1. 查看 `GOOGLE_API_SETUP.md` 詳細說明
            2. 設定 Google Service Account
            3. 重新部署應用程式
            """)

    with tab3:
        # Edit expenses
        if api_status:
            if not df.empty:
                edit_expense_form(df)
            else:
                st.info("沒有資料可編輯")
        else:
            st.info("🔑 請先設定 Google Sheets API 以啟用編輯功能")

def show_dashboard(df):
    """Show the dashboard analytics (original functionality)"""

    # Sidebar filters
    st.sidebar.header("📋 Filters")

    # Date range filter
    min_date = df['date'].min().date()
    max_date = df['date'].max().date()

    date_range = st.sidebar.date_input(
        "Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date
    )

    # Account filter
    accounts = ['All'] + sorted(df['account'].dropna().unique().tolist())
    selected_account = st.sidebar.selectbox("Account", accounts)

    # Category filter
    categories = ['All'] + sorted(df['category_emoji'].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Category", categories)

    # Apply filters
    filtered_df = df.copy()

    # Date filter
    if len(date_range) == 2:
        start_date, end_date = date_range
        filtered_df = filtered_df[
            (filtered_df['date'].dt.date >= start_date) &
            (filtered_df['date'].dt.date <= end_date)
        ]

    # Account filter
    if selected_account != 'All':
        filtered_df = filtered_df[filtered_df['account'] == selected_account]

    # Category filter
    if selected_category != 'All':
        filtered_df = filtered_df[filtered_df['category_emoji'] == selected_category]

    # Summary metrics
    st.header("💰 Summary")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        total_spent = filtered_df['amount'].sum()
        st.metric(
            label="Total Spent",
            value=f"NT$ {total_spent:,.0f}"
        )

    with col2:
        avg_transaction = filtered_df['amount'].mean()
        st.metric(
            label="Avg Transaction",
            value=f"NT$ {avg_transaction:,.0f}"
        )

    with col3:
        transaction_count = len(filtered_df)
        st.metric(
            label="Transactions",
            value=f"{transaction_count:,}"
        )

    with col4:
        if len(filtered_df) > 0:
            days_span = (filtered_df['date'].max() - filtered_df['date'].min()).days + 1
            daily_avg = total_spent / max(days_span, 1)
            st.metric(
                label="Daily Average",
                value=f"NT$ {daily_avg:,.0f}"
            )

    # Main visualizations
    if len(filtered_df) > 0:
        show_visualizations(filtered_df)
    else:
        st.info("No data matches the selected filters.")

def show_visualizations(df):
    """Display main visualizations"""

    # Monthly spending trend
    st.header("📈 Monthly Spending Trends")

    monthly_spending = df.groupby('month_year')['amount'].sum().reset_index()
    monthly_spending['month_year'] = pd.to_datetime(monthly_spending['month_year'])

    fig_monthly = px.line(
        monthly_spending,
        x='month_year',
        y='amount',
        title='Monthly Spending Over Time',
        markers=True
    )
    fig_monthly.update_layout(
        xaxis_title="Month",
        yaxis_title="Amount (NT$)",
        hovermode='x unified'
    )

    st.plotly_chart(fig_monthly, use_container_width=True)

    # Category breakdown
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🏷️ Spending by Category")
        category_spending = df.groupby('category_emoji')['amount'].sum().sort_values(ascending=False)

        fig_pie = px.pie(
            values=category_spending.values,
            names=category_spending.index,
            title='Category Distribution'
        )
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        st.subheader("👥 Spending by Account")
        account_spending = df.groupby('account')['amount'].sum().sort_values(ascending=False)

        fig_bar = px.bar(
            x=account_spending.values,
            y=account_spending.index,
            orientation='h',
            title='Account Comparison'
        )
        fig_bar.update_layout(
            xaxis_title="Amount (NT$)",
            yaxis_title="Account"
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    # Recent transactions
    st.header("📝 Recent Transactions")

    # Show last 20 transactions
    recent_df = df.nlargest(20, 'date')[['date', 'category_emoji', 'category_type', 'amount', 'account', 'description', 'location']]
    recent_df['date'] = recent_df['date'].dt.strftime('%Y-%m-%d')
    recent_df['amount'] = recent_df['amount'].apply(lambda x: f"NT$ {x:,.0f}")

    st.dataframe(
        recent_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "date": "Date",
            "category_emoji": "Category",
            "category_type": "Type",
            "amount": "Amount",
            "account": "Account",
            "description": "Description",
            "location": "Location"
        }
    )

if __name__ == "__main__":
    if check_password():
        main()