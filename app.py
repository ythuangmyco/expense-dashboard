"""
📊 Personal Expense Dashboard
Real-time visualization of expense tracker data from Google Sheets
Mobile-first design with progressive enhancement
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import numpy as np

# Import our modules
from config import PAGE_CONFIG, COLORS
from auth import check_password, password_screen, auth_sidebar, init_session_state
from sheets_api import load_expense_data, get_sheets_api, refresh_data
from input_forms import quick_entry_section, expense_input_form, edit_expense_form

# Page configuration
st.set_page_config(**PAGE_CONFIG)

# Initialize session state
init_session_state()

# Custom CSS for mobile-first design
st.markdown("""
<style>
    /* Mobile-first responsive design */
    .main-header {
        text-align: center;
        padding: 1rem 0;
        background: linear-gradient(90deg, #FF6B6B, #4ECDC4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 2rem;
        font-weight: bold;
        margin-bottom: 2rem;
    }

    .metric-card {
        background: white;
        padding: 1rem;
        border-radius: 0.5rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        text-align: center;
    }

    .quick-entry-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
        gap: 0.5rem;
        margin: 1rem 0;
    }

    /* Improve mobile button sizing */
    .stButton > button {
        width: 100%;
        height: 3rem;
        font-size: 0.9rem;
    }

    /* Better mobile form layouts */
    .stSelectbox > div > div > div {
        font-size: 0.9rem;
    }

    /* Hide unnecessary streamlit elements for cleaner mobile view */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}

    @media (max-width: 768px) {
        .main-header {
            font-size: 1.5rem;
        }

        .block-container {
            padding-top: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }
</style>
""", unsafe_allow_html=True)


def show_header():
    """Display app header with branding"""
    st.markdown('<div class="main-header">💰 HuangLiu Family Expense</div>', unsafe_allow_html=True)


def show_api_status():
    """Show API connection status"""
    api = get_sheets_api()
    status = api.get_status()

    if status["api_available"]:
        st.success("🟢 連線正常 - 即時同步")
    else:
        st.warning("🟡 唯讀模式 - 使用 CSV 資料")
        if st.button("🔄 重新連接"):
            refresh_data()
            st.rerun()


def show_summary_metrics(df: pd.DataFrame):
    """Display key metrics in mobile-friendly layout"""
    if df.empty:
        st.info("📊 尚無支出資料")
        return

    st.subheader("📈 本月概況")

    # Calculate metrics
    current_month = datetime.now().month
    current_year = datetime.now().year

    # Filter current month data
    current_month_df = df[
        (df['date'].dt.month == current_month) &
        (df['date'].dt.year == current_year)
    ]

    # Calculate metrics
    total_this_month = current_month_df['amount'].sum() if not current_month_df.empty else 0
    total_transactions = len(current_month_df)
    avg_transaction = total_this_month / total_transactions if total_transactions > 0 else 0

    # Last month for comparison
    last_month = current_month - 1 if current_month > 1 else 12
    last_month_year = current_year if current_month > 1 else current_year - 1

    last_month_df = df[
        (df['date'].dt.month == last_month) &
        (df['date'].dt.year == last_month_year)
    ]
    last_month_total = last_month_df['amount'].sum() if not last_month_df.empty else 0

    # Display metrics in columns
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "本月總支出",
            f"NT${total_this_month:,.0f}",
            delta=f"NT${total_this_month - last_month_total:,.0f}" if last_month_total > 0 else None
        )

    with col2:
        st.metric(
            "交易次數",
            f"{total_transactions:,}",
            delta=f"{total_transactions - len(last_month_df)}" if not last_month_df.empty else None
        )

    with col3:
        st.metric(
            "平均單筆",
            f"NT${avg_transaction:,.0f}"
        )

    with col4:
        # Most frequent category this month
        if not current_month_df.empty and 'category_type' in current_month_df.columns:
            top_category = current_month_df['category_type'].value_counts().index[0]
            st.metric("主要支出", top_category)
        else:
            st.metric("主要支出", "無資料")


def show_recent_transactions(df: pd.DataFrame, limit: int = 10):
    """Display recent transactions"""
    if df.empty:
        return

    st.subheader("📋 最近交易")

    # Sort by date and get recent transactions
    recent_df = df.sort_values('date', ascending=False).head(limit)

    # Create display DataFrame
    display_df = recent_df.copy()
    display_df['日期'] = display_df['date'].dt.strftime('%m/%d')
    display_df['分類'] = display_df.get('category_emoji', '') + ' ' + display_df.get('category_type', '')
    display_df['金額'] = display_df['amount'].apply(lambda x: f"NT${x:,.0f}")

    # Display as table
    st.dataframe(
        display_df[['日期', '分類', 'description', '金額', 'account']].rename(columns={
            'description': '描述',
            'account': '帳戶'
        }),
        use_container_width=True,
        hide_index=True
    )


def show_visualizations(df: pd.DataFrame):
    """Display interactive charts"""
    if df.empty:
        st.info("📊 需要更多資料才能顯示圖表")
        return

    st.subheader("📊 支出分析")

    # Chart tabs
    chart_tab1, chart_tab2, chart_tab3 = st.tabs(["💰 分類分析", "📅 時間趨勢", "👤 帳戶分布"])

    with chart_tab1:
        # Category analysis
        if 'category_type' in df.columns:
            category_spending = df.groupby('category_type')['amount'].sum().sort_values(ascending=False)

            fig = px.pie(
                values=category_spending.values,
                names=category_spending.index,
                title="支出分類佔比",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig.update_layout(showlegend=True, height=400)
            st.plotly_chart(fig, use_container_width=True)

            # Top categories table
            st.caption("支出分類排行")
            category_df = pd.DataFrame({
                '分類': category_spending.index,
                '金額': category_spending.values,
                '佔比': (category_spending.values / category_spending.sum() * 100).round(1)
            })
            category_df['金額'] = category_df['金額'].apply(lambda x: f"NT${x:,.0f}")
            category_df['佔比'] = category_df['佔比'].apply(lambda x: f"{x}%")
            st.dataframe(category_df, hide_index=True, use_container_width=True)

    with chart_tab2:
        # Time trends
        if 'date' in df.columns:
            # Monthly spending trend
            monthly_spending = df.groupby(df['date'].dt.to_period('M'))['amount'].sum()

            fig = px.line(
                x=monthly_spending.index.astype(str),
                y=monthly_spending.values,
                title="月度支出趨勢",
                labels={'x': '月份', 'y': '金額 (NT$)'}
            )
            fig.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig, use_container_width=True)

            # Weekly pattern
            df['weekday'] = df['date'].dt.day_name()
            weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            weekday_spending = df.groupby('weekday')['amount'].mean().reindex(weekday_order)

            fig = px.bar(
                x=['週一', '週二', '週三', '週四', '週五', '週六', '週日'],
                y=weekday_spending.values,
                title="週間消費模式 (平均)",
                labels={'x': '星期', 'y': '平均金額 (NT$)'}
            )
            fig.update_layout(showlegend=False, height=300)
            st.plotly_chart(fig, use_container_width=True)

    with chart_tab3:
        # Account distribution
        if 'account' in df.columns:
            account_spending = df.groupby('account')['amount'].sum()

            fig = px.bar(
                x=account_spending.index,
                y=account_spending.values,
                title="帳戶支出分布",
                labels={'x': '帳戶', 'y': '總金額 (NT$)'}
            )
            fig.update_layout(showlegend=False, height=400)
            st.plotly_chart(fig, use_container_width=True)


def main_dashboard():
    """Main dashboard page"""
    st.title("📊 支出總覽")

    # Load data
    with st.spinner("📊 載入資料中..."):
        df = load_expense_data()

    if df.empty:
        st.warning("📊 目前沒有支出資料")
        st.info("💡 請使用「新增支出」頁面開始記錄您的支出")
        return

    # Show summary metrics
    show_summary_metrics(df)

    st.divider()

    # Two column layout for desktop, single column for mobile
    col1, col2 = st.columns([2, 1])

    with col1:
        show_visualizations(df)

    with col2:
        show_recent_transactions(df)


def add_expense_page():
    """Add new expense page"""
    st.title("➕ 新增支出")

    # Load current data for smart suggestions
    with st.spinner("📊 載入資料中..."):
        df = load_expense_data()

    # Quick entry section
    quick_expense = quick_entry_section(df)
    if quick_expense:
        # Quick entry was selected, add it
        api = get_sheets_api()
        success = api.add_expense(quick_expense)
        if success:
            st.success(f"✅ 快速新增: {quick_expense['description']} - NT${quick_expense['amount']:,.0f}")
            # Refresh data
            st.cache_data.clear()
        else:
            st.error("❌ 新增失敗")

    st.divider()

    # Detailed form
    expense_input_form(df)


def edit_expense_page():
    """Edit expenses page"""
    st.title("✏️ 編輯支出")

    # Load data
    with st.spinner("📊 載入資料中..."):
        df = load_expense_data()

    # Edit form
    edit_expense_form(df)


def main():
    """Main application"""
    # Authentication check
    if not check_password():
        password_screen()
        return

    # Show header
    show_header()

    # Show API status
    show_api_status()

    # Main navigation tabs (mobile-first order)
    tab1, tab2, tab3 = st.tabs(["📊 總覽", "➕ 新增", "✏️ 編輯"])

    with tab1:
        main_dashboard()

    with tab2:
        add_expense_page()

    with tab3:
        edit_expense_page()

    # Auth sidebar
    auth_sidebar()

    # Footer
    with st.sidebar:
        st.divider()
        st.caption("💡 家庭支出追蹤系統")
        st.caption("🏠 HuangLiu Family")

        # Data refresh button
        if st.button("🔄 重新整理資料"):
            refresh_data()
            st.success("✅ 資料已重新整理")


if __name__ == "__main__":
    main()