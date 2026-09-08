"""
📊 Personal Expense Dashboard
Real-time visualization of expense tracker data from Google Sheets
Mobile-first design with progressive enhancement

總覽 (main_dashboard) follows PLAN_fx_and_overview.md §3: one period control,
a hero metric with a named comparison window, a static stat strip, top-3
category bars, the last 5 rows, and everything else behind collapsed
expanders. All arithmetic lives in overview.py (pure pandas, unit-tested);
this module only renders.
"""

import calendar
import html
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Import our modules
import overview as ov
from config import (
    COMPARISON_LABEL,
    COUNTRY_FLAG,
    OVERVIEW_MORE_PERIODS,
    OVERVIEW_PERIODS,
    PAGE_CONFIG,
    TRIP_ACTIVE_GRACE_DAYS,
)
from helpers import fmt_orig, fmt_pct, fmt_twd, today_local
from auth import check_password, password_screen, auth_sidebar, init_session_state
from sheets_api import load_expense_data, get_sheets_api, refresh_data, reconnect
from input_forms import expense_input_form, edit_expense_form

# Page configuration
st.set_page_config(**PAGE_CONFIG)

# Initialize session state
init_session_state()

# Custom CSS for mobile-first design (PLAN §3.2 chrome; static tiles use
# Streamlit's CSS variables so they follow the light/dark theme — G12).
st.markdown("""
<style>
    .main-header {
        text-align: center;
        line-height: 36px;
        height: 36px;
        background: linear-gradient(90deg, #FF6B6B, #4ECDC4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 1.25rem;
        font-weight: bold;
        margin-bottom: 0.5rem;
    }

    /* Static overview tiles (stat strip) */
    .ov-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 0.5rem;
        margin: 0.25rem 0 0.75rem 0;
    }
    .ov-tile {
        background: var(--secondary-background-color);
        color: var(--text-color);
        border-radius: 0.5rem;
        padding: 0.55rem 0.7rem;
        min-width: 0;
        overflow: hidden;
    }
    .ov-tile .ov-k {
        font-size: 0.75rem;
        opacity: 0.7;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ov-tile .ov-v {
        font-size: 1.05rem;
        font-weight: 600;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ov-tile .ov-s {
        font-size: 0.75rem;
        opacity: 0.7;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }

    /* Top-3 category bars */
    .ov-bars { margin: 0.25rem 0 0.5rem 0; color: var(--text-color); }
    .ov-bar-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0.5rem; align-items: baseline; margin-bottom: 0.15rem; }
    .ov-bar-name { font-size: 0.9rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ov-bar-amt { font-size: 0.9rem; font-weight: 600; white-space: nowrap; }
    .ov-bar-track { height: 6px; background: var(--secondary-background-color); border-radius: 3px; margin-bottom: 0.45rem; overflow: hidden; }
    .ov-bar-fill { height: 100%; background: var(--primary-color); border-radius: 3px; }
    .ov-bar-more { font-size: 0.8rem; opacity: 0.7; }

    /* Hide unnecessary streamlit elements for cleaner mobile view */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    @media (max-width: 768px) {
        .block-container {
            /* Keep >= Streamlit's fixed header height (3.75rem) so the title is not hidden */
            padding-top: 4.5rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }

    @media (max-width: 640px) {
        /* dataframe hover toolbar (search/download/fullscreen) is noise on a phone */
        [data-testid="stElementToolbar"] { display: none; }
    }

    @media (min-width: 640px) {
        .ov-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Session-state keys for 總覽 (one canonical period; widgets write it via callbacks)
# ---------------------------------------------------------------------------
PERIOD_KEY = "ov_period"            # {label, start, end, country}
SEG_KEY = "ov_seg"                  # segmented control (今天/本週/本月/本年/更多…)
MORE_KEY = "ov_more"                # pills inside the popover (上月/最近7天/最近30天/全部)
CUSTOM_START_KEY = "ov_custom_start"
CUSTOM_END_KEY = "ov_custom_end"
MORE_LABEL = OVERVIEW_PERIODS[-1]   # "更多…"
CUSTOM_LABEL = ov.CUSTOM_LABEL      # "自訂範圍"
TRIP_LABEL = ov.TRIP_LABEL          # "旅行"
DEFAULT_PERIOD = "本月"
FILTER_KEYS = {
    "accounts": "ov_f_accounts",
    "type_1": "ov_f_type1",
    "categories": "ov_f_categories",
    "countries": "ov_f_countries",
}
POPOVER_KEYS = (MORE_KEY, CUSTOM_START_KEY, CUSTOM_END_KEY)
PLOTLY_CONFIG = {"staticPlot": True, "displayModeBar": False}
TREND_DAILY_MAX_DAYS = 45
RECENT_ROWS = 5


def show_header():
    """Display app header with branding (one 36 px line)."""
    st.markdown('<div class="main-header">💰 HuangLiu Family Expense</div>', unsafe_allow_html=True)


def show_api_status():
    """API connection status: a sidebar dot when healthy, the amber 唯讀 banner otherwise."""
    api = get_sheets_api()
    status = api.get_status()

    if status["api_available"]:
        with st.sidebar:
            st.caption("🟢 Google Sheets API 連線正常")
        return

    st.warning("🟡 唯讀模式 - 使用 CSV 資料")

    # Show detailed status information
    with st.expander("🔍 連線狀態詳情"):
        st.write(f"**Sheet ID**: {status['sheet_id']}")
        st.write(f"**Worksheet GID**: {status['worksheet_gid']}")
        st.write(f"**API 可用**: {status['api_available']}")
        st.write(f"**工作表連接**: {status['worksheet_connected']}")
        st.info("💡 若要啟用新增/編輯功能，請設定 Google Sheets API")
        st.code("需要在 Streamlit Cloud 的 Settings → Secrets 中添加 Google 服務帳戶憑證")

    if st.button("🔄 重新連接"):
        reconnect()  # rebuilds the SheetsAPI client and clears the data cache
        st.rerun()


# ---------------------------------------------------------------------------
# Frame helpers (every one tolerates a legacy frame without the FX columns — G15)
# ---------------------------------------------------------------------------

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


def _currency_series(df: pd.DataFrame) -> pd.Series:
    """Upper-cased ISO code per row; '' for TWD-native rows and legacy frames."""
    if df is None or 'currency' not in df.columns:
        return pd.Series('', index=df.index if df is not None else None, dtype=object)
    cur = df['currency'].fillna('').astype(str).str.strip().str.upper()
    return cur.where(cur != 'TWD', '')


def converted_mask(df: pd.DataFrame) -> pd.Series:
    """True for rows carrying a non-TWD 幣別 (converted rows); all-False on legacy frames."""
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    return _currency_series(df) != ''


def orig_labels(df: pd.DataFrame) -> pd.Series:
    """'SGD 12.50' per converted row, '' otherwise (helpers.fmt_orig)."""
    if df is None or df.empty or 'currency' not in df.columns:
        return pd.Series('', index=df.index if df is not None else None, dtype=object)
    cur = _currency_series(df)
    orig = pd.to_numeric(df['orig_amount'], errors='coerce') if 'orig_amount' in df.columns else pd.Series(np.nan, index=df.index)
    return pd.Series(
        [fmt_orig(c, o) if c else '' for c, o in zip(cur, orig)],
        index=df.index, dtype=object,
    )


def _sorted_desc(df: pd.DataFrame) -> pd.DataFrame:
    """Stable sort: date desc, then sheet_row desc (same-day rows keep sheet order)."""
    if df.empty:
        return df
    cols = [c for c in ("date", "sheet_row") if c in df.columns]
    return df.sort_values(cols, ascending=[False] * len(cols), kind="mergesort", na_position="last")


def _display_frame(df: pd.DataFrame, with_category: bool, with_account: bool) -> tuple:
    """(frame, column_config) for a transaction table; 原幣 column only when a converted row exists."""
    out = pd.DataFrame(index=df.index)
    out["日期"] = df["date"].dt.strftime("%m/%d").fillna("—")
    if with_category:
        out["分類"] = df["category_type"].map(ov.canonical_category)
    out["名稱"] = df["description"]
    out["金額"] = df["amount"]
    if with_account:
        out["帳戶"] = df["account"]
    config = {
        "日期": st.column_config.TextColumn("日期", width="small"),
        "名稱": st.column_config.TextColumn("名稱"),
        "金額": st.column_config.NumberColumn("金額", format="NT$%d"),
    }
    if bool(converted_mask(df).any()):
        out["原幣"] = orig_labels(df)
        config["原幣"] = st.column_config.TextColumn("原幣", width="small")
    return out, config


def _merge_orig_into_name(shown: pd.DataFrame, config: dict) -> None:
    """
    Fold 原幣 into 名稱 ('咖啡 · SGD 12.50') instead of keeping a sixth column.

    Measured at 390 px: six columns need 426 px inside a 322 px grid, so the
    original amount lands off-screen behind a horizontal scroller. Merging keeps
    it visible and the table within the phone's width (PLAN §3.2: no horizontal
    scroll), at the cost of the plan's separate 原幣 column.
    """
    if "原幣" not in shown.columns:
        return
    suffix = shown.pop("原幣")
    shown["名稱"] = [f"{n} · {o}" if o else n for n, o in zip(shown["名稱"], suffix)]
    config.pop("原幣", None)


# ---------------------------------------------------------------------------
# Period state (PLAN §3.2 "fixes the state trap": one canonical ov_period,
# every widget writes it from its own callback, no priority order)
# ---------------------------------------------------------------------------

def _set_period(label, start=None, end=None, country=None):
    st.session_state[PERIOD_KEY] = {"label": label, "start": start, "end": end, "country": country}


def _seg_value_for(label: str) -> str:
    return label if label in OVERVIEW_PERIODS else MORE_LABEL


KNOWN_LABELS = tuple(OVERVIEW_PERIODS[:-1]) + tuple(OVERVIEW_MORE_PERIODS) + (CUSTOM_LABEL, TRIP_LABEL)


def _init_period_state():
    current = st.session_state.get(PERIOD_KEY)
    if not isinstance(current, dict) or current.get("label") not in KNOWN_LABELS:
        _set_period(DEFAULT_PERIOD)
    # Seed the widget key instead of passing default= so callbacks may assign it later
    # without Streamlit's "created with a default value but also had its value set" warning.
    if SEG_KEY not in st.session_state:
        st.session_state[SEG_KEY] = _seg_value_for(st.session_state[PERIOD_KEY]["label"])


def _on_segment_change():
    label = st.session_state.get(SEG_KEY)
    if label is None:  # tapping the active option deselects it: keep the current period
        st.session_state[SEG_KEY] = _seg_value_for(st.session_state[PERIOD_KEY]["label"])
        return
    if label == MORE_LABEL:
        return  # the popover controls pick the period
    _set_period(label)
    for key in POPOVER_KEYS:
        st.session_state.pop(key, None)


def _on_more_change():
    label = st.session_state.get(MORE_KEY)
    if label is None:
        current = st.session_state[PERIOD_KEY]["label"]
        if current in OVERVIEW_MORE_PERIODS:
            st.session_state[MORE_KEY] = current
        return
    _set_period(label)
    st.session_state[SEG_KEY] = MORE_LABEL


def _on_custom_change():
    start = st.session_state.get(CUSTOM_START_KEY)
    end = st.session_state.get(CUSTOM_END_KEY)
    _set_period(CUSTOM_LABEL, start, end)
    st.session_state[SEG_KEY] = MORE_LABEL
    st.session_state.pop(MORE_KEY, None)


def _on_trip_view(country, start, end):
    _set_period(TRIP_LABEL, start, end, country)
    st.session_state[SEG_KEY] = MORE_LABEL
    st.session_state.pop(MORE_KEY, None)


def _on_choose_more(label):
    """Empty-state buttons (上月 / 全部): same effect as picking the pill."""
    _set_period(label)
    st.session_state[SEG_KEY] = MORE_LABEL
    st.session_state[MORE_KEY] = label


def current_period(df: pd.DataFrame, today: date) -> dict:
    """Resolve ov_period into concrete dates. Presets are re-resolved every run (day may change)."""
    p = st.session_state[PERIOD_KEY]
    label, country = p["label"], p.get("country")
    if label == CUSTOM_LABEL:
        start, end = p.get("start"), p.get("end")
        valid = start is not None and end is not None and end >= start
    elif label == TRIP_LABEL:
        start, end = p.get("start"), p.get("end")
        valid = start is not None and end is not None and end >= start
    else:
        start, end = ov.resolve_period(label, today, df)
        valid = start is not None
    return {"label": label, "start": start, "end": end, "country": country, "valid": valid}


def period_control(df: pd.DataFrame, trips: list, today: date):
    """Row 1: segmented control + 更多期間 popover (pills, 自訂範圍, trip list)."""
    _init_period_state()
    with st.container(horizontal=True, vertical_alignment="center"):
        st.segmented_control(
            "期間", options=OVERVIEW_PERIODS, key=SEG_KEY,
            on_change=_on_segment_change, label_visibility="collapsed",
        )
        with st.popover("更多期間"):
            st.pills("更多期間", options=OVERVIEW_MORE_PERIODS, key=MORE_KEY,
                     on_change=_on_more_change, label_visibility="collapsed")
            st.caption("自訂範圍")
            c1, c2 = st.columns(2)
            with c1:
                st.date_input("開始日期", value=today.replace(day=1), key=CUSTOM_START_KEY,
                              on_change=_on_custom_change)
            with c2:
                st.date_input("結束日期", value=today, key=CUSTOM_END_KEY,
                              on_change=_on_custom_change)
            if trips:
                st.caption("旅行")
                for i, trip in enumerate(trips):
                    with st.container(horizontal=True, vertical_alignment="center"):
                        st.write(f"{ov.trip_label(trip)} · {fmt_twd(trip.total)}")
                        if not trip.is_pending:
                            st.button("查看", key=f"ov_trip_{i}", on_click=_on_trip_view,
                                      args=(trip.country, trip.start, trip.end))


# ---------------------------------------------------------------------------
# Filters (🔍 篩選 — no 全部 sentinel; empty = no filter)
# ---------------------------------------------------------------------------

def _options(df: pd.DataFrame, column: str, canonical=None) -> list:
    if df is None or df.empty or column not in df.columns:
        return []
    values = df[column].dropna().astype(str).str.strip()
    if canonical is not None:
        values = values.map(canonical)
    return sorted(v for v in values.unique().tolist() if v and v.lower() != "nan")


def _prune_filter_state(key, options):
    """Drop stored selections no longer offered; assign only when something was pruned."""
    if key in st.session_state:
        current = st.session_state[key]
        if current is None:
            return
        current = list(current)
        kept = [v for v in current if v in options]
        if kept != current:
            st.session_state[key] = kept


def current_filters() -> dict:
    """Filter selections from session state (keyed widgets: state == latest frontend value)."""
    out = {}
    for name, key in FILTER_KEYS.items():
        value = st.session_state.get(key)
        if value:
            out[name] = list(value) if not isinstance(value, str) else [value]
    return out


def _clear_filters():
    for key in FILTER_KEYS.values():
        st.session_state.pop(key, None)


def filter_badge(filters: dict, period: dict):
    """Static echo of active filters + 清除 (badge when available, caption otherwise)."""
    parts = []
    if period["label"] == TRIP_LABEL and period.get("country"):
        flag = COUNTRY_FLAG.get(period["country"], "")
        parts.append(f"{flag} {period['country']}".strip())
    for name in ("accounts", "type_1", "categories", "countries"):
        for v in filters.get(name, []):
            parts.append(str(v))
    if not parts:
        return
    text = "篩選: " + " · ".join(parts)
    with st.container(horizontal=True, vertical_alignment="center"):
        if hasattr(st, "badge"):
            st.badge(text)
        else:
            st.caption(text)
        if filters:
            st.button("清除", key="ov_clear_filters", on_click=_clear_filters, type="tertiary")


def filter_expander(df: pd.DataFrame):
    """🔍 篩選: pills 帳戶 / 類型, multiselect 分類 (canonical) / 國家. Fixed keys survive period changes."""
    with st.expander("🔍 篩選", expanded=False):
        accounts = _options(df, "account")
        types = [t for t in (ov.DAILY_TYPE, ov.TRAVEL_TYPE) if t in _options(df, "type_1")] or _options(df, "type_1")
        categories = _options(df, "category_type", ov.canonical_category)
        countries = _options(df, "country")
        _prune_filter_state(FILTER_KEYS["accounts"], accounts)
        _prune_filter_state(FILTER_KEYS["type_1"], types)
        _prune_filter_state(FILTER_KEYS["categories"], categories)
        _prune_filter_state(FILTER_KEYS["countries"], countries)
        st.pills("帳戶", options=accounts, selection_mode="multi", key=FILTER_KEYS["accounts"])
        st.pills("類型", options=types, selection_mode="multi", key=FILTER_KEYS["type_1"])
        st.multiselect("分類", options=categories, key=FILTER_KEYS["categories"], placeholder="全部分類")
        st.multiselect("國家", options=countries, key=FILTER_KEYS["countries"], placeholder="全部國家")
        st.caption("未選 = 不篩選")


# ---------------------------------------------------------------------------
# Cached summary
# ---------------------------------------------------------------------------

def _filters_key(filters: dict) -> tuple:
    return tuple(sorted((k, tuple(v) if isinstance(v, (list, tuple)) else v) for k, v in filters.items()))


@st.cache_data(ttl=60, show_spinner=False)
def _cached_summary(df: pd.DataFrame, start, end, filters_key: tuple) -> dict:
    return ov.period_summary(df, start, end, dict((k, list(v) if isinstance(v, tuple) else v) for k, v in filters_key))


def period_summary(df: pd.DataFrame, start, end, filters: dict) -> dict:
    """overview.period_summary cached on (df, period, filters) — filters carry _label/_today hints."""
    try:
        return _cached_summary(df, start, end, _filters_key(filters))
    except Exception:
        return ov.period_summary(df, start, end, filters)


def _effective_filters(period: dict, filters: dict, today: date) -> dict:
    out = dict(filters)
    if period["label"] == TRIP_LABEL and period.get("country"):
        out["countries"] = [period["country"]]
    out["_label"] = period["label"]
    out["_today"] = today
    return out


# ---------------------------------------------------------------------------
# Screen 1
# ---------------------------------------------------------------------------

def _span_text(start: date, end: date) -> str:
    fmt = "%m/%d" if start.year == end.year else "%Y/%m/%d"
    if start == end:
        return start.strftime(fmt)
    return f"{start.strftime(fmt)}–{end.strftime(fmt)}"


def _period_title(period: dict) -> str:
    label, country = period["label"], period.get("country")
    if label == TRIP_LABEL and country:
        name = f"{COUNTRY_FLAG.get(country, '')} {country} 旅行".strip()
    else:
        name = label
    return f"{name}支出 · {_span_text(period['start'], period['end'])}"


def _signed_twd(n: int) -> str:
    text = fmt_twd(abs(int(n)))
    if n > 0:
        return "+" + text
    if n < 0:
        return "-" + text
    return text


def show_hero(df: pd.DataFrame, period: dict, filters: dict, summary: dict, today: date):
    """Row 2: st.metric hero — total, delta vs the named comparison window, sparkline, caption."""
    label, start, end = period["label"], period["start"], period["end"]
    cstart, cend, comp_label = ov.comparison_window(label, start, end)
    comp = period_summary(df, cstart, cend, filters) if cstart is not None else None
    has_comp = comp is not None and comp["count"] > 0

    delta = None
    delta_color = "inverse"
    delta_arrow = "auto"
    description = None
    if has_comp:
        diff = summary["total"] - comp["total"]
        if comp["total"] > 0:
            delta = f"{fmt_pct(diff / comp['total'])} ({_signed_twd(diff)})"
        else:
            delta = _signed_twd(diff)
        if diff == 0:
            delta_color, delta_arrow = "off", "off"
        description = f"比{comp_label}"

    filtered = ov.apply_filters(df, filters)
    daily = ov.daily_series(filtered, start, end)
    chart = daily["total"].tolist() if len(daily) > 1 else None

    st.metric(
        label=_period_title(period),
        value=fmt_twd(summary["total"]),
        delta=delta,
        delta_color=delta_color,
        delta_arrow=delta_arrow,
        delta_description=description,
        border=True,
        chart_data=chart,
        chart_type="bar" if chart is not None and len(chart) <= 7 else "line",
    )

    parts = [f"日均 {fmt_twd(summary['daily_avg'])}"]
    if summary.get("projected_month_end") is not None and summary["days"] < _days_in_month(start):
        parts.append(f"照此步調月底約 {fmt_twd(summary['projected_month_end'])}")
    if label == "本月":
        pstart, pend = ov.resolve_period("上月", today)
        prev = period_summary(df, pstart, pend, filters)
        if prev["count"]:
            parts.append(f"上月全月 {fmt_twd(prev['total'])}")
    if not has_comp:
        parts.append("無前期資料" if comp_label else "無比較期間")
    st.caption(" · ".join(parts))


def _days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def show_active_trip_badge(trips: list, today: date):
    trip = ov.active_trip(trips, today)
    if trip is None:
        return
    flag = COUNTRY_FLAG.get(trip.country, "")
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown(f"{flag} **正在旅行中** · {trip.country} {trip.start:%m/%d}– {fmt_twd(trip.in_trip_total)}")
        st.button("查看", key="ov_trip_active", on_click=_on_trip_view,
                  args=(trip.country, trip.start, trip.end))


def _tile(k: str, v: str, s: str = "") -> str:
    sub = f'<div class="ov-s">{html.escape(s)}</div>' if s else ""
    return f'<div class="ov-tile"><div class="ov-k">{html.escape(k)}</div><div class="ov-v">{html.escape(v)}</div>{sub}</div>'


def _fx_chips(fx: dict) -> str:
    return " · ".join(fmt_orig(c, v) for c, v in fx.items())


def show_stat_strip(summary: dict):
    """Row 3: static HTML tiles — 今天, per-account, and 旅行/日常 when the period has 旅行 rows."""
    tiles = [_tile("今天", fmt_twd(summary["today_total"]), f"{summary['today_count']} 筆")]
    accounts = summary["by_account"]
    if accounts:
        items = list(accounts.items())
        first = items[0]
        rest = " / ".join(f"{k} {fmt_twd(v)}" for k, v in items[1:])
        tiles.append(_tile("帳戶", f"{first[0]} {fmt_twd(first[1])}", rest))
    travel = summary["by_type1"].get(ov.TRAVEL_TYPE, 0)
    if travel > 0:
        tiles.append(_tile(ov.TRAVEL_TYPE, fmt_twd(travel), _fx_chips(summary["fx_by_currency"])))
        tiles.append(_tile(ov.DAILY_TYPE, fmt_twd(summary["by_type1"].get(ov.DAILY_TYPE, 0))))
    st.markdown('<div class="ov-grid">' + "".join(tiles) + "</div>", unsafe_allow_html=True)


def show_top_categories(summary: dict):
    """Row 4: three static bar rows + 「其他 N 類 NT$…」."""
    top = summary["top_categories"][:3]
    if not top:
        return
    rows = []
    for name, total, share in top:
        pct = max(0.0, min(1.0, float(share)))
        rows.append(
            '<div class="ov-bar-row">'
            f'<span class="ov-bar-name">{html.escape(name or "未分類")}</span>'
            f'<span class="ov-bar-amt">{html.escape(fmt_twd(total))} · {round(pct * 100)}%</span>'
            '</div>'
            f'<div class="ov-bar-track"><div class="ov-bar-fill" style="width:{pct * 100:.1f}%"></div></div>'
        )
    if summary["other_categories_count"]:
        rows.append(f'<div class="ov-bar-more">其他 {summary["other_categories_count"]} 類 '
                    f'{html.escape(fmt_twd(summary["other_categories_total"]))}</div>')
    st.markdown('<div class="ov-bars">' + "".join(rows) + "</div>", unsafe_allow_html=True)


def show_recent_list(df: pd.DataFrame, limit: int = RECENT_ROWS):
    """Row 5: the last N rows of the (normalised, filtered, sliced) period frame."""
    df = ov.apply_filters(df, None)  # normalised copy: legacy frames gain the FX columns
    if df.empty:
        return
    recent = _sorted_desc(df).head(limit)
    shown, config = _display_frame(recent, with_category=False, with_account=False)
    _merge_orig_into_name(shown, config)
    st.dataframe(shown, hide_index=True, width="stretch", height="auto", row_height=34,
                 column_config=config)


def show_empty_period(period: dict):
    """One st.info + two buttons; nothing else renders (the filter expander stays so filters survive)."""
    st.info(f"{period['label']}尚無支出 — 試試 上月 或 全部")
    with st.container(horizontal=True):
        st.button("上月", key="ov_empty_prev", on_click=_on_choose_more, args=("上月",))
        st.button("全部", key="ov_empty_all", on_click=_on_choose_more, args=("全部",))


# ---------------------------------------------------------------------------
# Expanders
# ---------------------------------------------------------------------------

def show_period_transactions(df: pd.DataFrame, summary: dict):
    df = ov.apply_filters(df, None)
    n = len(df)
    with st.expander(f"📋 本期全部交易 ({n} 筆)", expanded=False):
        if n == 0:
            st.caption("本期無交易")
            return
        shown, config = _display_frame(_sorted_desc(df), with_category=True, with_account=True)
        _merge_orig_into_name(shown, config)
        st.dataframe(shown, hide_index=True, width="stretch", height=min(n, 12) * 34 + 38,
                     row_height=34, column_config=config)
        largest = summary.get("largest")
        if largest:
            when = largest["date"].strftime("%m/%d") if largest.get("date") else "—"
            st.caption(f"本期 {n} 筆 · 最大一筆 {fmt_twd(largest['amount'])} {largest['description']} ({when})")
        else:
            st.caption(f"本期 {n} 筆")


def _line_figure(series: dict, height: int) -> go.Figure:
    fig = go.Figure()
    for name, frame in series.items():
        if frame is None or frame.empty:
            continue
        fig.add_trace(go.Scatter(x=[str(i) for i in frame["day_index"]], y=frame["cumulative"],
                                 mode="lines", name=name))
    fig.update_xaxes(type="category", title_text="第幾天")
    fig.update_yaxes(rangemode="tozero", title_text="累計 NT$")
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=1.1, x=0), dragmode=False)
    return fig


def _bar_figure(monthly: pd.DataFrame, today: date, height: int) -> go.Figure:
    current = today.strftime("%Y-%m")
    labels = [f"{m} 進行中" if m == current else m for m in monthly["month"]]
    fig = go.Figure(go.Bar(x=labels, y=monthly["total"], name="月支出"))
    fig.update_xaxes(type="category")
    fig.update_yaxes(rangemode="tozero", title_text="NT$")
    fig.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), showlegend=False, dragmode=False)
    return fig


def show_trend_expander(df: pd.DataFrame, period: dict, filters: dict, today: date):
    """📈 趨勢: ≤45 days → cumulative 本期 vs 比較期; longer → monthly bars (+ table for 本年/全部)."""
    label, start, end = period["label"], period["start"], period["end"]
    days = (end - start).days + 1
    with st.expander("📈 趨勢", expanded=False):
        filtered = ov.apply_filters(df, filters)
        if days <= TREND_DAILY_MAX_DAYS:
            series = {"本期": ov.cumulative_series(filtered, start, end)}
            cstart, cend, comp_label = ov.comparison_window(label, start, end)
            if cstart is not None:
                comp = ov.cumulative_series(filtered, cstart, cend)
                if comp["total"].sum() > 0:
                    series[comp_label] = comp
            st.plotly_chart(_line_figure(series, 260), width="stretch", config=PLOTLY_CONFIG)
        else:
            sliced = ov.slice_period(filtered, start, end)
            monthly = ov.monthly_series(sliced)
            if monthly.empty:
                st.caption("本期無交易")
                return
            st.plotly_chart(_bar_figure(monthly, today, 260), width="stretch", config=PLOTLY_CONFIG)
            if label in ("本年", ov.ALL_LABEL):
                table = pd.DataFrame({"月份": monthly["month"], "支出": monthly["total"], "筆數": monthly["count"]})
                st.dataframe(table, hide_index=True, width="stretch",
                             height=min(len(table), 12) * 34 + 38, row_height=34,
                             column_config={"支出": st.column_config.NumberColumn("支出", format="NT$%d")})


def show_accounts_expander(df: pd.DataFrame, summary: dict):
    """👤 帳戶與類型: account × category table + 日常/旅行 split."""
    with st.expander("👤 帳戶與類型", expanded=False):
        valid = df[df["amount"].notna()] if "amount" in df.columns else df
        if valid.empty:
            st.caption("本期無交易")
            return
        cats = valid["category_type"].map(ov.canonical_category).replace({"": "未分類"})
        pivot = pd.crosstab(cats, valid["account"], values=valid["amount"], aggfunc="sum").fillna(0)
        pivot = pivot.round().astype("int64")
        pivot["合計"] = pivot.sum(axis=1)
        pivot = pivot.sort_values("合計", ascending=False)
        table = pivot.reset_index().rename(columns={"category_type": "分類", "row_0": "分類"})
        table.columns = ["分類"] + list(table.columns[1:])
        config = {c: st.column_config.NumberColumn(c, format="NT$%d") for c in table.columns[1:]}
        st.dataframe(table, hide_index=True, width="stretch",
                     height=min(len(table), 12) * 34 + 38, row_height=34, column_config=config)
        split = summary["by_type1"]
        st.caption(" · ".join(f"{k} {fmt_twd(v)}" for k, v in split.items()))


def _row_line(row: dict) -> str:
    when = row["date"].strftime("%m/%d") if row.get("date") else "—"
    amt = fmt_twd(row["amount"]) if row.get("amount") is not None else "—"
    return f"{when} {row.get('description') or ''} {amt}".strip()


def show_data_check_expander(summary: dict):
    """🧹 資料檢查 (period-scoped): unparseable / zero rows listed, FX audit counts."""
    with st.expander("🧹 資料檢查", expanded=False):
        st.caption(f"範圍：{_span_text(summary['start'], summary['end'])} · {summary['count']} 筆")
        st.write(f"**無法解析的金額**: {summary['unparseable_count']} 筆")
        for row in summary["unparseable_rows"][:10]:
            st.caption("· " + _row_line(row))
        st.write(f"**零金額記錄**: {summary['zero_count']} 筆")
        for row in summary["zero_rows"][:10]:
            st.caption("· " + _row_line(row))
        st.write(f"**已換算外幣**: {summary['converted_count']} 筆")
        st.write(f"**換算不一致**: {summary['inconsistent_count']} 筆")
        if summary["inconsistent_count"]:
            st.caption("⚠️ 金額 ≠ 原幣金額 × 匯率（差 > NT$1）— 請在「編輯」修正：" +
                       "、".join(_row_line(r) for r in summary["inconsistent_rows"][:10]) +
                       ("…" if summary["inconsistent_count"] > 10 else ""))
        st.write(f"**未標幣別**: {summary['unlabeled_currency_count']} 筆")
        if summary["unlabeled_currency_count"]:
            st.caption("ℹ️ 國外消費但未填幣別（視為台幣）；外幣小計因此為部分金額")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main_dashboard():
    """總覽: period → hero → stat strip → top-3 → last 5 → expanders (PLAN §3.1)."""
    with st.spinner("📊 載入資料中..."):
        df = load_expense_data()

    if df is None or df.empty:
        st.warning("📊 目前沒有支出資料")
        st.info("💡 請使用「新增支出」頁面開始記錄您的支出")
        return

    today = today_local()
    trips = ov.detect_trips(df, today)

    period_control(df, trips, today)
    period = current_period(df, today)
    filters = current_filters()

    if not period["valid"]:
        st.error("⚠️ 結束日期不可早於開始日期")
        filter_badge(filters, period)
        filter_expander(df)
        return

    eff = _effective_filters(period, filters, today)
    summary = period_summary(df, period["start"], period["end"], eff)
    filter_badge(filters, period)

    if summary["count"] == 0:
        show_empty_period(period)
        filter_expander(df)
        return

    show_hero(df, period, eff, summary, today)
    show_active_trip_badge(trips, today)
    show_stat_strip(summary)
    show_top_categories(summary)

    period_df = ov.slice_period(ov.apply_filters(df, eff), period["start"], period["end"])
    show_recent_list(period_df)

    show_period_transactions(period_df, summary)
    show_trend_expander(df, period, eff, today)
    show_accounts_expander(period_df, summary)
    filter_expander(df)
    show_data_check_expander(summary)


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

    # Main navigation tabs (新增 first — the in-shop path; key keeps the tab across reruns)
    tab1, tab2, tab3 = st.tabs(["➕ 新增", "✏️ 編輯", "📊 總覽"], key="main_tab")

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
