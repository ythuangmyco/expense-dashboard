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
from datetime import datetime, timedelta, date
import calendar
import numpy as np

# Import our modules
from config import PAGE_CONFIG, COLORS
from helpers import today_local
from auth import check_password, password_screen, auth_sidebar, init_session_state
from sheets_api import load_expense_data, get_sheets_api, refresh_data, reconnect
from input_forms import expense_input_form, edit_expense_form

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
            /* Keep >= Streamlit's fixed header height (3.75rem) so the title is not hidden */
            padding-top: 4.5rem;
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
        st.success("🟢 Google Sheets API 連線正常 - 可新增/編輯支出")
    else:
        st.warning("🟡 唯讀模式 - 使用 CSV 資料")

        # Show detailed status information
        with st.expander("🔍 連線狀態詳情"):
            st.write(f"**Sheet ID**: {status['sheet_id']}")
            st.write(f"**Worksheet GID**: {status['worksheet_gid']}")
            st.write(f"**API 可用**: {status['api_available']}")
            st.write(f"**工作表連接**: {status['worksheet_connected']}")

            if not status["api_available"]:
                st.info("💡 若要啟用新增/編輯功能，請設定 Google Sheets API")
                st.code("需要在 Streamlit Cloud 的 Settings → Secrets 中添加 Google 服務帳戶憑證")

        if st.button("🔄 重新連接"):
            reconnect()  # rebuilds the SheetsAPI client and clears the data cache
            st.rerun()


def numeric_amount(df: pd.DataFrame, drop_na: bool = True) -> pd.DataFrame:
    """Return a copy of df whose 'amount' column is numeric (never mutates the input).

    Unparseable amounts become NaN and are dropped by default so that sums,
    means and groupbys never concatenate strings or silently count NaN as 0.
    """
    if df is None or df.empty or 'amount' not in df.columns:
        return pd.DataFrame() if df is None else df.copy()
    out = df.copy()
    amt = out['amount']
    if not pd.api.types.is_numeric_dtype(amt):
        amt = amt.astype(str).str.replace(',', '', regex=False).str.replace('NT$', '', regex=False).str.strip()
    out['amount'] = pd.to_numeric(amt, errors='coerce')
    if drop_na:
        out = out[out['amount'].notna()]
    return out


def _clamp_day(year: int, month: int, day: int) -> date:
    """Build a date, clamping the day to the month's length (e.g. Mar 31 -> Feb 28)."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def get_comparison_period(start_date, end_date, df, period_type=None):
    """Get the comparison period for (start_date, end_date).

    Calendar presets compare against the previous calendar unit:
      本月 -> previous month, day 1 .. same day-of-month (clamped)
      上月 -> the full calendar month before start_date
      本年 -> previous year, Jan 1 .. same month/day (clamped)
    Every other preset uses the trailing window of equal length.
    """
    if not start_date or not end_date or end_date < start_date:
        return None, None, None

    if period_type == "上月":
        comp_end = start_date - timedelta(days=1)
        comp_start = comp_end.replace(day=1)
    elif period_type == "本月":
        comp_end_full = start_date - timedelta(days=1)  # last day of previous month
        comp_start = comp_end_full.replace(day=1)
        comp_end = min(comp_end_full, _clamp_day(comp_start.year, comp_start.month, end_date.day))
    elif period_type == "本年":
        comp_start = date(start_date.year - 1, 1, 1)
        comp_end = _clamp_day(end_date.year - 1, end_date.month, end_date.day)
    else:
        period_length = (end_date - start_date).days + 1
        comp_end = start_date - timedelta(days=1)
        comp_start = comp_end - timedelta(days=period_length - 1)

    # Filter comparison data
    if df is not None and 'date' in df.columns and not df.empty:
        try:
            comp_start_dt = pd.to_datetime(comp_start)
            comp_end_dt = pd.to_datetime(comp_end) + pd.Timedelta(days=1)

            comp_df = df[
                (df['date'] >= comp_start_dt) &
                (df['date'] < comp_end_dt)
            ]
            return comp_start, comp_end, comp_df
        except:
            pass

    return comp_start, comp_end, pd.DataFrame()


def show_data_quality_info(df: pd.DataFrame):
    """Show information about data quality and what was filtered"""
    if df.empty:
        return

    with st.expander("📊 資料品質資訊", expanded=False):
        st.caption("了解資料載入和篩選過程")

        # Basic stats
        st.write(f"**有效記錄數量**: {len(df)}")

        if 'amount' in df.columns:
            amt = numeric_amount(df, drop_na=False)['amount']
            valid_amounts = int(amt.notna().sum())
            zero_amounts = int((amt == 0).sum())
            invalid_amounts = int(amt.isna().sum())
            st.write(f"**有效金額記錄**: {valid_amounts}")
            st.write(f"**零金額記錄**: {zero_amounts}")
            if invalid_amounts:
                st.write(f"**無法解析的金額**: {invalid_amounts}")

        if 'date' in df.columns:
            valid_dates = df['date'].notna().sum()
            st.write(f"**有效日期記錄**: {valid_dates}")

            # Show date range
            if valid_dates > 0:
                min_date = df['date'].min().strftime('%Y-%m-%d')
                max_date = df['date'].max().strftime('%Y-%m-%d')
                st.write(f"**日期範圍**: {min_date} 至 {max_date}")

        # Show recent filtered data info
        st.caption("💡 被篩選的記錄通常是空白行、無效日期或無效金額的資料")


def _fmt_delta(change, fmt="{:+,.0f}"):
    """Format a metric delta; exact-zero (after rounding) -> None so st.metric shows no arrow."""
    if change is None:
        return None
    try:
        rounded = round(float(change))
    except (TypeError, ValueError):
        return None
    if rounded == 0:
        return None
    return fmt.format(rounded)


def show_summary_metrics(df: pd.DataFrame, start_date=None, end_date=None, original_df=None, period_type=None):
    """Display key metrics for the specified period with comparison.

    original_df is the comparison base: it must already carry the same
    category/account filters as df (only the date range differs).
    """
    if df.empty:
        st.info("📊 所選期間內無支出資料")
        return

    # Check if required columns exist
    if 'date' not in df.columns or 'amount' not in df.columns:
        st.warning(f"📊 資料結構不完整。可用欄位: {list(df.columns)}")
        return

    # Determine period description
    if start_date and end_date:
        if start_date == end_date:
            period_desc = f"📈 {start_date.strftime('%Y/%m/%d')} 當日統計"
        else:
            period_desc = f"📈 {start_date.strftime('%Y/%m/%d')} - {end_date.strftime('%Y/%m/%d')} 期間統計"
    else:
        period_desc = "📈 整體統計"

    st.subheader(period_desc)

    # Calculate metrics for the filtered period (df is already filtered)
    try:
        # Work on a numeric copy; never mutate the caller's (cached) frame.
        df = numeric_amount(df)
        if df.empty:
            st.info("📊 所選期間內沒有可解析的金額")
            return

        total_amount = float(df['amount'].sum())
        total_transactions = len(df)
        avg_transaction = float(total_amount / total_transactions) if total_transactions > 0 else 0.0

        # Calculate daily average if we have a date range
        daily_avg = 0.0
        if start_date and end_date:
            days_in_period = (end_date - start_date).days + 1
            daily_avg = float(total_amount / days_in_period) if days_in_period > 0 else 0.0

        # Get top categories
        top_category = "無資料"
        category_amount = 0
        if 'category_type' in df.columns and not df.empty:
            category_summary = df.groupby('category_type')['amount'].sum().sort_values(ascending=False)
            if not category_summary.empty:
                top_category = category_summary.index[0]
                category_amount = category_summary.iloc[0]

        # Get comparison data if we have the original dataframe and date range
        comp_metrics = {}
        if original_df is not None and start_date and end_date:
            comp_start, comp_end, comp_df = get_comparison_period(start_date, end_date, original_df, period_type)
            comp_df = numeric_amount(comp_df) if comp_df is not None else pd.DataFrame()
            if not comp_df.empty:
                comp_total = float(comp_df['amount'].sum())
                comp_transactions = len(comp_df)
                comp_avg = float(comp_total / comp_transactions) if comp_transactions > 0 else 0.0
                comp_daily = float(comp_total / ((comp_end - comp_start).days + 1)) if comp_start and comp_end else 0.0

                # Calculate changes
                comp_metrics = {
                    'total_change': float(total_amount - comp_total),
                    'total_change_pct': float(((total_amount - comp_total) / comp_total * 100)) if comp_total > 0 else 0.0,
                    'transactions_change': int(total_transactions - comp_transactions),
                    'avg_change': float(avg_transaction - comp_avg),
                    'daily_change': float(daily_avg - comp_daily)
                }

    except Exception as e:
        st.error(f"統計計算錯誤: {str(e)}")
        return

    # Display metrics in columns
    col1, col2, col3, col4 = st.columns(4)

    # Spending going up is bad -> 'inverse' colours; a transaction count is neutral -> 'off'
    with col1:
        st.metric(
            "總支出",
            f"NT${total_amount:,.0f}",
            delta=_fmt_delta(comp_metrics.get('total_change')),
            delta_color="inverse"
        )

    with col2:
        st.metric(
            "交易次數",
            f"{total_transactions:,}",
            delta=_fmt_delta(comp_metrics.get('transactions_change'), fmt="{:+,}"),
            delta_color="off"
        )

    with col3:
        st.metric(
            "平均單筆",
            f"NT${avg_transaction:,.0f}",
            delta=_fmt_delta(comp_metrics.get('avg_change')),
            delta_color="inverse"
        )

    with col4:
        if daily_avg > 0:
            st.metric(
                "日均支出",
                f"NT${daily_avg:,.0f}",
                delta=_fmt_delta(comp_metrics.get('daily_change')),
                delta_color="inverse"
            )
        else:
            st.metric(
                "主要支出",
                top_category[:8] + "..." if len(str(top_category)) > 8 else str(top_category)
            )

    # Additional period stats
    if total_transactions > 0:
        col1, col2 = st.columns(2)

        with col1:
            st.caption(f"💡 最高支出類別: {top_category} (NT${category_amount:,.0f})")

        with col2:
            if start_date and end_date:
                days = (end_date - start_date).days + 1
                st.caption(f"📊 統計期間: {days} 天")


def show_recent_transactions(df: pd.DataFrame, limit: int = 15):
    """Display recent transactions with improved styling"""
    if df.empty:
        return

    # Check if required columns exist
    required_cols = ['date', 'amount']
    if not all(col in df.columns for col in required_cols):
        st.info("📋 最近交易資料不完整")
        return

    st.subheader("📋 最近交易")

    try:
        # Sort by date and get recent transactions
        recent_df = df.sort_values('date', ascending=False).head(limit)

        # Create display DataFrame with better formatting
        display_df = recent_df.copy()
        display_df['📅 日期'] = display_df['date'].dt.strftime('%m/%d')

        # Handle category display - check what columns exist
        if 'category_type' in display_df.columns:
            display_df['🏷️ 分類'] = display_df['category_type']
        else:
            display_df['🏷️ 分類'] = '未分類'

        # Safe amount formatting (unparseable -> shown as '—', not a fake NT$0)
        numeric_amt = numeric_amount(recent_df, drop_na=False)['amount']

        def safe_amount_format(x):
            try:
                if pd.isna(x):
                    return "—"
                return f"NT${float(x):,.0f}"
            except Exception:
                return "—"

        display_df['💰 金額'] = numeric_amt.apply(safe_amount_format)

        # Create columns list based on what's available
        display_cols = ['📅 日期', '🏷️ 分類']

        if 'description' in display_df.columns:
            display_df['📝 描述'] = display_df['description'].fillna('')
            display_cols.append('📝 描述')

        display_cols.append('💰 金額')

        if 'account' in display_df.columns:
            display_df['👤 帳戶'] = display_df['account'].fillna('')
            display_cols.append('👤 帳戶')

        # Display as styled table
        st.dataframe(
            display_df[display_cols],
            use_container_width=True,
            hide_index=True,
            height=400
        )

        # Show summary info
        total_shown = len(recent_df)
        total_amount = float(numeric_amt.fillna(0).sum())
        st.caption(f"📊 顯示最近 {total_shown} 筆交易，總額 NT${total_amount:,.0f}")

    except Exception as e:
        st.error(f"最近交易顯示錯誤: {str(e)}")


def show_visualizations(df: pd.DataFrame):
    """Display interactive charts"""
    if df.empty:
        st.info("📊 需要更多資料才能顯示圖表")
        return

    # Check required columns
    required_cols = ['amount']
    if not all(col in df.columns for col in required_cols):
        st.warning(f"📊 圖表功能需要完整資料。缺少欄位: {[col for col in required_cols if col not in df.columns]}")
        return

    # Own numeric copy: charts must not depend on another function's mutation
    df = numeric_amount(df)
    if df.empty:
        st.info("📊 需要更多資料才能顯示圖表")
        return

    st.subheader("📊 支出分析")

    # Category Analysis Section
    if 'category_type' in df.columns:
        st.markdown("### 💰 支出分類分析")

        col1, col2 = st.columns([1, 1])

        with col1:
            category_spending = df.groupby('category_type')['amount'].sum().sort_values(ascending=False)

            fig = px.pie(
                values=category_spending.values,
                names=category_spending.index,
                title="支出分類佔比",
                color_discrete_sequence=px.colors.qualitative.Set3
            )
            fig.update_layout(
                showlegend=True,
                height=450,
                title_font_size=16,
                font=dict(size=12)
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown("**📋 分類排行榜**")
            try:
                # Ensure values are numeric for calculations
                category_values = pd.to_numeric(category_spending.values, errors='coerce')
                category_values = pd.Series(category_values).fillna(0)  # Convert to Series first
                category_total = float(category_values.sum())

                if category_total > 0:
                    percentages = (category_values / category_total * 100).round(1)
                else:
                    percentages = pd.Series([0.0] * len(category_values))

                category_df = pd.DataFrame({
                    '🏷️ 分類': category_spending.index,
                    '💰 金額': category_values,
                    '📊 佔比': percentages
                })
                category_df['💰 金額'] = category_df['💰 金額'].apply(lambda x: f"NT${float(x):,.0f}")
                category_df['📊 佔比'] = category_df['📊 佔比'].apply(lambda x: f"{float(x):,.1f}%")

                st.dataframe(
                    category_df,
                    hide_index=True,
                    use_container_width=True,
                    height=350
                )
            except Exception as e:
                st.error(f"分類統計計算錯誤: {str(e)}")

    st.markdown("---")

    # Time Trends Section
    if 'date' in df.columns:
        st.markdown("### 📅 時間趨勢分析")

        # Monthly spending trend
        monthly_spending = df.groupby(df['date'].dt.to_period('M'))['amount'].sum()

        fig = px.line(
            x=monthly_spending.index.astype(str),
            y=monthly_spending.values,
            title="📈 月度支出趨勢",
            labels={'x': '月份', 'y': '金額 (NT$)'},
            markers=True
        )
        fig.update_layout(
            showlegend=False,
            height=400,
            title_font_size=16,
            xaxis_title="月份",
            yaxis_title="支出金額 (NT$)"
        )
        st.plotly_chart(fig, use_container_width=True)

        # Weekly and Account Analysis
        col1, col2 = st.columns([1, 1])

        with col1:
            # Weekly pattern
            df['weekday'] = df['date'].dt.day_name()
            weekday_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            weekday_spending = df.groupby('weekday')['amount'].mean().reindex(weekday_order)

            fig = px.bar(
                x=['週一', '週二', '週三', '週四', '週五', '週六', '週日'],
                y=weekday_spending.values,
                title="📊 週間消費模式",
                labels={'x': '星期', 'y': '平均金額 (NT$)'},
                color_discrete_sequence=['#FF6B6B']
            )
            fig.update_layout(
                showlegend=False,
                height=350,
                title_font_size=14
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            # Account distribution
            if 'account' in df.columns:
                account_spending = df.groupby('account')['amount'].sum()

                fig = px.bar(
                    x=account_spending.index,
                    y=account_spending.values,
                    title="👤 帳戶支出分布",
                    labels={'x': '帳戶', 'y': '總金額 (NT$)'},
                    color_discrete_sequence=['#4ECDC4']
                )
                fig.update_layout(
                    showlegend=False,
                    height=350,
                    title_font_size=14
                )
                st.plotly_chart(fig, use_container_width=True)


def get_period_dates(period_type, df):
    """Get start and end dates for different period types (Asia/Taipei calendar)"""
    today = today_local()

    if period_type == "今天":
        return today, today
    elif period_type == "最近7天":
        return today - timedelta(days=6), today
    elif period_type == "本週":
        # Monday of current week
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period_type == "本月":
        return today.replace(day=1), today
    elif period_type == "上月":
        # First day of last month
        first_day_current = today.replace(day=1)
        last_day_prev = first_day_current - timedelta(days=1)
        first_day_prev = last_day_prev.replace(day=1)
        return first_day_prev, last_day_prev
    elif period_type == "最近30天":
        return today - timedelta(days=29), today
    elif period_type == "本年":
        return today.replace(month=1, day=1), today
    elif period_type == "全部期間":
        if 'date' in df.columns and not df.empty:
            try:
                return df['date'].min().date(), df['date'].max().date()
            except:
                pass
        return today, today
    else:  # Custom
        return None, None


def _filter_options(df, column, all_label):
    """Option list for a filter widget: all_label + sorted non-empty values of the column."""
    if column not in df.columns or df.empty:
        return [all_label]
    values = df[column].dropna().astype(str).str.strip()
    values = sorted(v for v in values.unique().tolist() if v and v.lower() != 'nan')
    return [all_label] + values


def _prune_filter_state(key, options, default):
    """Drop stored selections no longer offered; fall back to default if nothing remains."""
    if key in st.session_state:
        current = list(st.session_state[key])
        kept = [v for v in current if v in options]
        new_value = kept if kept else list(default)
        # Only assign when something was actually pruned: assigning on every
        # run while the widget also has default= makes Streamlit show its
        # "created with a default value but also had its value set" warning.
        if new_value != current:
            st.session_state[key] = new_value


def additional_filters(df):
    """Additional filtering options for categories and accounts.

    Pass the FULL (not period-sliced) dataframe: options are then stable
    across period changes, and the widgets keep fixed keys so a selection
    survives a period switch instead of resetting to 全部.
    """
    with st.expander("🔍 進階篩選", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            # Category filter
            available_categories = _filter_options(df, 'category_type', "全部分類")
            _prune_filter_state("cat_filter", available_categories, ["全部分類"])
            selected_categories = st.multiselect(
                "支出分類",
                options=available_categories,
                default=["全部分類"],
                key="cat_filter",
                help="選擇要顯示的支出分類"
            )

        with col2:
            # Account filter
            available_accounts = _filter_options(df, 'account', "全部帳戶")
            _prune_filter_state("acct_filter", available_accounts, ["全部帳戶"])
            selected_accounts = st.multiselect(
                "帳戶",
                options=available_accounts,
                default=["全部帳戶"],
                key="acct_filter",
                help="選擇要顯示的帳戶"
            )

    return list(selected_categories or []), list(selected_accounts or [])


def apply_additional_filters(df, selected_categories, selected_accounts):
    """Apply category and account filters to the dataframe"""
    filtered_df = df.copy()

    # Apply category filter
    if "全部分類" not in selected_categories and selected_categories:
        if 'category_type' in df.columns:
            filtered_df = filtered_df[filtered_df['category_type'].isin(selected_categories)]

    # Apply account filter
    if "全部帳戶" not in selected_accounts and selected_accounts:
        if 'account' in df.columns:
            filtered_df = filtered_df[filtered_df['account'].isin(selected_accounts)]

    return filtered_df


def time_period_selector(df):
    """Enhanced time period selection with presets"""
    st.subheader("📅 時間範圍選擇")

    # Period preset options
    period_options = [
        "今天", "最近7天", "本週", "本月", "上月",
        "最近30天", "本年", "全部期間", "自定義範圍"
    ]

    # Initialize session state for period selection (the widget key IS the state;
    # no index= recomputation, no post-widget assignment -> ids stay stable and
    # consecutive selections are never dropped)
    if 'selected_period' not in st.session_state or st.session_state.selected_period not in period_options:
        st.session_state.selected_period = "本月"

    col1, col2 = st.columns([2, 1])

    with col1:
        selected_period = st.selectbox(
            "選擇時間範圍",
            options=period_options,
            key="selected_period",
            help="選擇預設的時間範圍或自定義"
        )

    with col2:
        # Quick period buttons: on_click callbacks run before the next script run,
        # so setting the keyed widget's state here is legal and needs no st.rerun()
        st.markdown("**快速選擇:**")

        def _set_period(value):
            st.session_state.selected_period = value

        quick_buttons = [
            ("今天", "查看今日支出"), ("最近7天", "查看最近一週支出"),
            ("本週", "查看本週支出"), ("本月", "查看本月支出"),
            ("上月", "查看上月支出"), ("本年", "查看本年度支出"),
        ]
        for i in range(0, len(quick_buttons), 2):
            row_cols = st.columns(2)
            for col, (label, help_text) in zip(row_cols, quick_buttons[i:i + 2]):
                with col:
                    st.button(
                        label,
                        help=help_text,
                        use_container_width=True,
                        key=f"quick_period_{label}",
                        on_click=_set_period,
                        args=(label,),
                    )

    # Get dates based on selection
    if selected_period == "自定義範圍":
        st.caption("🗓️ 自定義日期範圍")
        col1, col2 = st.columns(2)

        # Default to current month (Asia/Taipei) if no data
        today = today_local()
        default_start = today.replace(day=1)
        default_end = today

        # If we have data, use actual date range for defaults
        if 'date' in df.columns and not df.empty:
            try:
                min_date = df['date'].min().date()
                max_date = df['date'].max().date()
                default_start = min_date
                default_end = max_date
            except:
                pass

        with col1:
            start_date = st.date_input(
                "開始日期",
                value=default_start,
                key="custom_start_date",
                help="選擇篩選的開始日期"
            )

        with col2:
            end_date = st.date_input(
                "結束日期",
                value=default_end,
                key="custom_end_date",
                help="選擇篩選的結束日期"
            )

        # Validate ordering; main_dashboard treats None dates as 'no query'
        if start_date and end_date and end_date < start_date:
            st.error("⚠️ 結束日期不可早於開始日期")
            return None, None, selected_period
    else:
        start_date, end_date = get_period_dates(selected_period, df)

        # Show selected period info
        if start_date and end_date:
            if start_date == end_date:
                st.info(f"📅 **{selected_period}**: {start_date.strftime('%Y年%m月%d日')}")
            else:
                st.info(f"📅 **{selected_period}**: {start_date.strftime('%Y/%m/%d')} 至 {end_date.strftime('%Y/%m/%d')}")

    return start_date, end_date, selected_period


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

    # Enhanced time period selection
    start_date, end_date, selected_period = time_period_selector(df)

    # Additional filtering options are rendered BEFORE any early return so the
    # keyed multiselects exist on every run and keep their selection even
    # while a custom range is invalid. Options come from the FULL df so the
    # widgets keep their identity across period changes.
    selected_categories, selected_accounts = additional_filters(df)

    if not start_date or not end_date:
        st.warning("⚠️ 請選擇有效的日期範圍")
        return

    # Filter data by date range
    filtered_df = df.copy()
    if 'date' in df.columns and not df.empty:
        try:
            # Convert dates for filtering
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1)  # Include end date

            filtered_df = df[
                (df['date'] >= start_datetime) &
                (df['date'] < end_datetime)
            ]

        except Exception as e:
            st.warning(f"⚠️ 日期篩選錯誤: {str(e)}")
            filtered_df = df  # Use original data if filtering fails

    filtered_df = apply_additional_filters(filtered_df, selected_categories, selected_accounts)

    # Comparison base: all dates, but the SAME category/account filters as the current period
    comparison_base = apply_additional_filters(df, selected_categories, selected_accounts)

    # Show comprehensive filter summary
    filter_parts = [f"**{selected_period}**"]

    if "全部分類" not in selected_categories and selected_categories:
        filter_parts.append(f"分類: {', '.join(selected_categories)}")

    if "全部帳戶" not in selected_accounts and selected_accounts:
        filter_parts.append(f"帳戶: {', '.join(selected_accounts)}")

    if len(filtered_df) != len(df):
        filter_summary = " | ".join(filter_parts)
        st.success(f"📊 {filter_summary} - {len(filtered_df)}/{len(df)} 筆記錄")
    else:
        st.info(f"📊 顯示所有 {len(df)} 筆記錄")

    # Show summary metrics for filtered period with comparison
    show_summary_metrics(filtered_df, start_date, end_date, comparison_base, selected_period)

    # Show data quality information
    show_data_quality_info(df)

    # Show comparison period info if available
    if start_date and end_date:
        comp_start, comp_end, comp_df = get_comparison_period(start_date, end_date, comparison_base, selected_period)
        if comp_df is not None and not comp_df.empty:
            st.caption(f"📊 與前期比較 ({comp_start.strftime('%m/%d')} - {comp_end.strftime('%m/%d')}, {len(comp_df)} 筆記錄)")

    st.divider()

    # Show recent transactions first
    show_recent_transactions(filtered_df)

    st.divider()

    # Then show visualizations
    show_visualizations(filtered_df)


def add_expense_page():
    """Add new expense page"""
    st.title("➕ 新增支出")

    # Load current data for smart suggestions
    with st.spinner("📊 載入資料中..."):
        df = load_expense_data()

    # Main expense input form
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

    # Confirmation for a refresh triggered on the previous run (survives st.rerun)
    if st.session_state.pop("data_refreshed", False):
        st.toast("✅ 資料已重新整理")

    # Show API status
    show_api_status()

    # Main navigation tabs (updated order)
    tab1, tab2, tab3 = st.tabs(["➕ 新增", "✏️ 編輯", "📊 總覽"])

    with tab1:
        add_expense_page()

    with tab2:
        edit_expense_page()

    with tab3:
        main_dashboard()

    # Auth sidebar
    auth_sidebar()

    # Footer
    with st.sidebar:
        st.divider()
        st.caption("💡 家庭支出追蹤系統")
        st.caption("🏠 HuangLiu Family")

        # Data refresh button
        if st.button("🔄 重新整理資料", key="sidebar_refresh_data"):
            refresh_data()
            st.session_state["data_refreshed"] = True
            st.rerun()  # tabs already rendered with cached data; rerun to show fresh data


if __name__ == "__main__":
    main()