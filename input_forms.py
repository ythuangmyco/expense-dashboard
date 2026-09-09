"""
Mobile-first input forms for quick expense entry
Focus on speed and ease of use on mobile devices
"""

import time

import streamlit as st
import pandas as pd
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, NamedTuple, Optional, Tuple
from config import (
    TYPE_1_OPTIONS, CATEGORIES, ACCOUNTS, LOCATIONS_MAP,
    DEFAULT_TYPE_1, DEFAULT_COUNTRY, DEFAULT_LOCATION, DEFAULT_ACCOUNT,
    COUNTRY_CURRENCY, CURRENCY_OPTIONS, CURRENCY_META,
)
import fx
from helpers import parse_amount, today_local, to_twd, q6, fmt_orig
from sheets_api import get_sheets_api
from auth import get_current_user


# Quick entry section removed as requested

# Seconds during which an identical (date, account, description, amount,
# currency, orig_amount) payload is treated as an accidental double submission.
DUPLICATE_SUBMIT_WINDOW = 120
EMPTY_LABEL = "（空白）"
FX_HELP_FIRST_USE = "輸入後點空白處即更新台幣"
FX_MISSING_COLUMNS_CAPTION = "⚠️ 工作表尚未新增幣別欄位"
FX_DROPPED_WARNING = "⚠️ 工作表尚未有 幣別/原幣金額/匯率 欄位，此筆只儲存了台幣金額"


def _text(value) -> str:
    """Text cell as loaded from the sheet: NaN/None/'nan' -> ''."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "nat") else text


def _options_with(options: List[str], stored: str) -> Tuple[List[str], int]:
    """
    Options list for a selectbox that must show the stored value as-is.
    A stored value missing from the config list (including '') is inserted
    at the top instead of silently resetting to option 0.
    """
    options = list(options)
    if stored in options:
        return options, options.index(stored)
    return [stored] + options, 0


def _fmt_blank(value) -> str:
    return value if value else EMPTY_LABEL


def _country_location_selectors(key_prefix: str, stored_country: Optional[str] = None,
                                stored_location: Optional[str] = None) -> Tuple[str, str]:
    """
    國家 / 地點 selectboxes. These live OUTSIDE st.form so a country change
    reruns the script and the location list follows immediately.
    """
    countries = list(LOCATIONS_MAP.keys())
    if stored_country is None:
        country_options = countries
        country_index = countries.index(DEFAULT_COUNTRY) if DEFAULT_COUNTRY in countries else 0
    else:
        country_options, country_index = _options_with(countries, stored_country)

    loc_col1, loc_col2 = st.columns(2)
    with loc_col1:
        country = st.selectbox(
            "國家",
            options=country_options,
            index=country_index,
            format_func=_fmt_blank,
            key=f"{key_prefix}_country",
        )

    available_locations = list(LOCATIONS_MAP.get(country, ["其他"]))
    if stored_location is not None and country == stored_country:
        location_options, location_index = _options_with(available_locations, stored_location)
    else:
        location_options = available_locations
        location_index = 0
        if country == DEFAULT_COUNTRY and DEFAULT_LOCATION in available_locations:
            location_index = available_locations.index(DEFAULT_LOCATION)

    with loc_col2:
        # Key includes the country so the widget is re-created (and reset)
        # whenever the country changes instead of keeping a foreign value.
        location = st.selectbox(
            "地點",
            options=location_options,
            index=location_index,
            format_func=_fmt_blank,
            key=f"{key_prefix}_location_{country}",
        )
    return country, location


# ---------------------------------------------------------------------------
# 💱 外幣換算 card (PLAN_fx_and_overview.md §2.2 / §2.5)
# ---------------------------------------------------------------------------
class FxStored(NamedTuple):
    """FX cells of an existing row as loaded ('' / None = TWD-native)."""
    currency: str
    orig_amount: Optional[float]
    fx_rate: Optional[float]
    amount: Optional[float]          # stored 金額 (for 保留原台幣金額 / 帳單金額)


class FxState(NamedTuple):
    """Result of an active conversion. ``orig_amount``/``twd`` are None until an amount is typed."""
    currency: str
    orig_amount: Optional[Decimal]
    rate_eff: Optional[Decimal]      # the rate actually used/stored (fee folded in, 6 dp)
    twd: Optional[int]
    quote: Optional[fx.Quote]
    fee_on: bool
    keep_twd: bool = False           # edit: 保留原台幣金額 applied
    statement: Optional[int] = None  # edit: 帳單金額 applied


def _fx_float(value) -> Optional[float]:
    """Numeric FX cell (orig_amount / fx_rate) as float, None when blank/NaN/unparseable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        num = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return None if num != num else num


def _fmt_rate(rate) -> str:
    """6-dp Decimal rendered without trailing zeros: 25.281600 -> '25.2816'."""
    try:
        d = q6(rate)
    except ValueError:
        return "?"
    text = f"{d:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _has_fx_columns(df) -> Optional[bool]:
    """sheets_api.has_fx_columns via the module (tolerates stubbed sheets_api in tests)."""
    import sheets_api as _sa
    fn = getattr(_sa, "has_fx_columns", None)
    if fn is None:
        return None
    try:
        return fn(df)
    except Exception:
        return None


def _fx_refresh_callback(currency: str, on_date, rate_key: str, flag_key: str,
                        fresh_key: str, df=None) -> None:
    """
    ↻ 重新取得匯率 (on_click, runs before the rerun): evict the cached quote,
    fetch a fresh one and ASSIGN it to the 匯率 widget's session_state key.

    Deleting the key is not enough: the widget keeps its identity, so the
    browser keeps the user's override and sends it back on the next rerun
    (the preview would show the fresh rate while the save used the old one).
    An assignment is flagged ``value_changed`` -> the proto carries
    ``set_value`` and the frontend adopts the fresh rate.
    The fresh Quote is stashed under ``fresh_key`` so the rerun renders it
    as ✅ live instead of re-reading it from the cache as 🕒.
    """
    fx.invalidate(currency, on_date)
    quote = fx.get_quote(currency, on_date, df=df)
    if quote is not None:
        st.session_state[rate_key] = float(quote.rate)
        st.session_state[fresh_key] = quote
    elif rate_key in st.session_state:
        del st.session_state[rate_key]
    st.session_state[flag_key] = True


def _fx_block(kp: str, country: str, gen: int, *, stored: Optional[FxStored] = None,
              on_date, show_statement: bool = False, df=None) -> Optional[FxState]:
    """
    The 💱 外幣換算 card. Everything here lives OUTSIDE st.form so each change
    reruns immediately and the ≈ NT$ preview follows the typed amount.

    Add form (stored is None), widget keys per plan §2.2:
      {kp}_currency_{country} · {kp}_fx_amount_{gen} · {kp}_fx_rate_{ccy}_{quote_date}
      {kp}_fx_fee_{country} · {kp}_fx_refresh
    Edit form (stored given; ``gen`` is the sheet row), keys per plan §2.5:
      {kp}_currency_{row} · {kp}_fx_amount_{row} · {kp}_fx_rate_{row}_{ccy}
      {kp}_fx_fee_{row} · {kp}_keep_twd_{row} · {kp}_stmt_{row} · {kp}_fx_refresh_{row}

    Returns None when no conversion is active (幣別 = TWD): no FX widget beyond
    the 幣別 selectbox is instantiated and fx.get_quote is never called.
    Add form, 國家 with no foreign currency (台灣): returns None BEFORE any
    widget — the domestic path has zero new widgets (§2.1). A domestic
    foreign-currency purchase is entered via the 編輯 opt-in card instead.
    """
    edit = stored is not None
    tok = gen
    on_date = on_date or today_local()
    # Leading underscore: internal bookkeeping, deliberately outside the
    # {kp}_fx_* widget-key namespace so it is never mistaken for widget state.
    seen_key = f"_fxseen_{kp}_{tok}"

    default_ccy = COUNTRY_CURRENCY.get(country, "TWD")
    if edit and stored.currency:
        default_ccy = stored.currency            # G4: stored currency wins over 國家
    if not edit and default_ccy == "TWD":
        st.session_state[seen_key] = "TWD"
        return None
    options = [default_ccy] + [c for c in CURRENCY_OPTIONS if c != default_ccy]
    if "TWD" not in options:
        options.append("TWD")
    ccy_key = f"{kp}_currency_{tok}" if edit else f"{kp}_currency_{country}"
    currency = st.selectbox("幣別 💱", options=options, index=0, key=ccy_key,
                            help="TWD = 直接輸入台幣金額")
    if not currency or currency == "TWD":
        st.session_state[seen_key] = "TWD"
        return None

    decimals, step = CURRENCY_META.get(currency, (2, 0.01))
    amount_key = f"{kp}_fx_amount_{tok}"
    fee_key = f"{kp}_fx_fee_{tok}" if edit else f"{kp}_fx_fee_{country}"
    flag_key = f"{kp}_fx_want_quote_{tok}"
    fresh_key = f"{kp}_fx_fresh_quote_{tok}"

    # ---- 原幣金額 --------------------------------------------------------
    stored_orig = stored.orig_amount if edit else None
    if stored_orig is not None and stored.currency == currency:
        amount_default = round(float(stored_orig), decimals)
    else:
        amount_default = None
    orig_widget = st.number_input(
        f"原幣金額 ({currency})",
        min_value=0.0,
        step=float(step),
        value=amount_default,
        format=f"%.{decimals}f",
        placeholder="請輸入原幣金額...",
        key=amount_key,
    )
    if orig_widget is None:
        st.caption(FX_HELP_FIRST_USE)

    # ---- quote (only when the stored rate cannot seed the widget) ---------
    stored_rate = stored.fx_rate if (edit and stored.currency == currency) else None
    if stored_rate is not None and stored_rate <= 0:
        stored_rate = None
    want_quote = (stored_rate is None) or bool(st.session_state.get(flag_key, False))
    # A quote fetched by the ↻ callback is consumed exactly once (this rerun).
    quote = st.session_state.pop(fresh_key, None)
    if not isinstance(quote, fx.Quote) or quote.currency != currency:
        quote = None

    # Only reach the network when the rate is actually being asked for. Streamlit
    # re-renders this tab on every interaction anywhere in the app, so fetching on
    # a plain render would put the rate chain on the critical path of an unrelated
    # click in 總覽. Asking for it means: the family picked a different country or
    # currency just now, or typed an amount to convert. On the first render of a
    # session the country is merely restored from last time, so we answer from the
    # cache / 上次使用 / the offline table and stay instant; the caption says which.
    seen = st.session_state.get(seen_key)
    allow_network = (seen is not None and seen != currency) or orig_widget is not None
    st.session_state[seen_key] = currency

    if quote is None and want_quote:
        if allow_network:
            with st.spinner("取得匯率中…"):
                quote = fx.get_quote(currency, on_date, df=df)
        else:
            quote = fx.get_quote(currency, on_date, df=df, allow_network=False)

    if edit:
        rate_key = f"{kp}_fx_rate_{tok}_{currency}"
    else:
        quote_date = quote.as_of.isoformat() if quote is not None else on_date.isoformat()
        rate_key = f"{kp}_fx_rate_{currency}_{quote_date}"
    if quote is not None:
        rate_default = float(quote.rate)
    elif stored_rate is not None:
        rate_default = float(q6(stored_rate))
    else:
        rate_default = None

    preview = st.container()          # ≈ NT$ metric + caption render above 進階

    with st.expander("▸ 進階", expanded=False):
        rate_widget = st.number_input(
            f"匯率 (1 {currency} = ? TWD)",
            min_value=0.0,
            step=0.000001,
            value=rate_default,
            format="%.6f",
            placeholder="請輸入匯率...",
            key=rate_key,
        )
        fee_on = bool(st.toggle("信用卡結匯 +1.5%", key=fee_key))
        st.button(
            "↻ 重新取得匯率",
            key=f"{kp}_fx_refresh_{tok}" if edit else f"{kp}_fx_refresh",
            on_click=_fx_refresh_callback,
            args=(currency, on_date, rate_key, flag_key, fresh_key, df),
        )

    keep_twd = False
    statement = None
    if edit and show_statement:
        if stored.amount is not None:
            keep_twd = bool(st.checkbox(
                "保留原台幣金額（反推匯率）",
                value=(not stored.currency),      # back-fill case: totals never move
                key=f"{kp}_keep_twd_{tok}",
                help="金額不變，匯率 = 金額 ÷ 原幣金額",
            ))
        stmt_widget = st.number_input(
            "💳 帳單金額 (TWD)",
            min_value=0.0,
            step=1.0,
            value=None,
            format="%.0f",
            placeholder="對帳後的台幣金額（選填）",
            key=f"{kp}_stmt_{tok}",
            help="輸入信用卡帳單上的台幣金額，匯率會自動反推",
        )
        if stmt_widget is not None and stmt_widget > 0:
            statement = int(round(float(stmt_widget)))

    # ---- arithmetic (never re-seeds a widget from session_state) ----------
    orig_amount = None
    if orig_widget is not None and orig_widget > 0:
        orig_amount = Decimal(str(orig_widget)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)

    rate_eff = None
    if rate_widget is not None and rate_widget > 0:
        rate_eff = fx.effective_rate(rate_widget, fee_on)

    twd = None
    if orig_amount is not None:
        if statement is not None:                       # rule (i): 帳單金額
            rate_eff = q6(Decimal(statement) / orig_amount)
            twd = statement
            keep_twd = False
        elif keep_twd and stored.amount is not None:    # rule (ii): 保留原台幣金額
            rate_eff = q6(Decimal(str(stored.amount)) / orig_amount)
            twd = int(round(float(stored.amount)))
        elif rate_eff is not None:                      # rule (iii): from the 6-dp rate
            twd = to_twd(orig_amount, rate_eff, decimals)

    with preview:
        if twd is not None:
            st.metric("≈ 台幣 (TWD)", f"NT${twd:,}")
        else:
            st.metric("≈ 台幣 (TWD)", "NT$ —")
        parts = []
        if rate_eff is not None:
            derived = statement is not None or (keep_twd and orig_amount is not None)
            parts.append(f"匯率 {_fmt_rate(rate_eff)}" + ("（含手續費）" if fee_on and not derived else ""))
        if statement is not None:
            parts.append("💳 依帳單金額反推")
        elif keep_twd and orig_amount is not None:
            parts.append("🔒 保留原台幣金額")
        elif quote is not None:
            parts.append(fx.freshness_caption(quote))
        elif stored_rate is not None:
            parts.append("💾 已儲存的匯率")
        else:
            parts.append(fx.freshness_caption(None))
        st.caption(" · ".join(parts))

    return FxState(currency, orig_amount, rate_eff, twd, quote, fee_on, keep_twd, statement)


def _fx_amount_info(state: FxState) -> None:
    """In-form replacement for the 金額 widget while a conversion is active."""
    if state.twd is not None and state.orig_amount is not None:
        st.info(f"金額 (TWD)：NT${state.twd:,} ← {fmt_orig(state.currency, state.orig_amount)}"
                f" × {_fmt_rate(state.rate_eff)}")
    elif state.orig_amount is None:
        st.info(f"金額 (TWD)：請先在上方輸入原幣金額 ({state.currency})")
    else:
        st.info("金額 (TWD)：匯率無效，請在「▸ 進階」輸入匯率")


def _fx_validation_error(state: FxState) -> Optional[str]:
    if state.orig_amount is None or state.orig_amount <= 0:
        return "請輸入原幣金額"
    if state.rate_eff is None or state.rate_eff <= 0 or state.twd is None:
        return "匯率無效"
    return None


def _write_warnings(api) -> List[str]:
    warnings = getattr(api, "last_write_warnings", None)
    if isinstance(warnings, (list, tuple)):
        return [str(w) for w in warnings if w]
    return []


def _sheet_currency(value) -> str:
    """幣別 as loaded: upper-cased ISO code; TWD/blank -> ''."""
    code = _text(value).upper()
    return "" if code == "TWD" else code


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
                descs = filtered_df['description'].map(_text)
                descriptions = descs[descs != ""].value_counts().head(5)
                suggestions["descriptions"] = descriptions.index.tolist()

            # Most common amounts
            if 'amount' in filtered_df.columns:
                # Ensure amounts are numeric; unparseable cells are ignored
                numeric_amounts = pd.to_numeric(filtered_df['amount'], errors='coerce').dropna()
                amounts = numeric_amounts.value_counts().head(3)
                suggestions["amounts"] = amounts.index.tolist()
                try:
                    mean_amount = numeric_amounts.mean()
                    suggestions["avg_amount"] = int(mean_amount) if mean_amount > 0 else 0
                except Exception:
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

    # Success message from the previous run (shown after the post-save rerun)
    flash = st.session_state.pop("add_expense_flash", None)
    if flash:
        st.success(flash)
    for warn in st.session_state.pop("add_expense_warnings", None) or []:
        st.warning(warn)

    # Generation counter: bumped after a confirmed successful write so the
    # in-form widgets get fresh keys (= reset) without clear_on_submit.
    gen = st.session_state.get("add_form_gen", 0)

    # Type_1 / category live outside the form so smart suggestions follow
    # the category the user actually picked.
    type_1 = st.selectbox(
        "類型 📅",
        options=TYPE_1_OPTIONS,
        index=TYPE_1_OPTIONS.index(DEFAULT_TYPE_1) if DEFAULT_TYPE_1 in TYPE_1_OPTIONS else 0,
        help="選擇支出類型",
        key="add_type_1",
    )

    # Type_2 selection (Specific category) - Display in Chinese
    category_type = st.selectbox(
        "分類 🏷️",
        options=CATEGORIES,
        help="選擇具體的支出類型",
        key="add_category",
    )

    # Get smart suggestions for this category
    suggestions = smart_suggestions(df, category_type)

    # Location selection (outside the form so 地點 follows 國家)
    st.caption("📍 地點資訊")
    country, location = _country_location_selectors("add")

    # 💱 外幣換算 card (outside the form). None when 國家=台灣 (no widget at
    # all) or 幣別=TWD: no FX widgets, no network. Quotes today's rate (§2.3).
    fx_state = _fx_block("add", country, gen, on_date=today_local(), df=df)
    if fx_state is not None and _has_fx_columns(df) is False:
        st.caption(FX_MISSING_COLUMNS_CAPTION)

    with st.form(f"expense_form_{gen}"):
        # First row: Date and Account
        col1, col2 = st.columns(2)
        with col1:
            expense_date = st.date_input(
                "日期 📅",
                value=today_local(),
                help="支出日期",
                key=f"add_date_{gen}",
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
                help="記帳帳戶",
                key=f"add_account_{gen}",
            )

        # Amount input (empty by default). In FX mode the keyed widget is
        # simply not instantiated; 金額 is the converted TWD figure.
        if fx_state is None:
            amount = st.number_input(
                "金額 💰",
                min_value=0,
                step=10,
                value=None,
                placeholder="請輸入金額...",
                help="支出金額",
                key=f"add_amount_{gen}",
            )
        else:
            _fx_amount_info(fx_state)
            amount = fx_state.twd

        # Show amount suggestions as text only
        if suggestions["amounts"]:
            try:
                # Safely convert amounts to integers
                safe_amounts = []
                for amt in suggestions['amounts'][:3]:
                    try:
                        safe_amounts.append(f'NT${int(float(amt))}')
                    except Exception:
                        safe_amounts.append(f'NT${amt}')
                st.caption("💡 常用金額: " + ", ".join(a.replace("$", "\\$") for a in safe_amounts))
            except Exception:
                st.caption("💡 常用金額建議暫時無法顯示")

        # Description input
        description = st.text_input(
            "描述 📝",
            placeholder="支出描述...",
            help="簡單描述這筆支出",
            key=f"add_description_{gen}",
        )

        # Show description suggestions as text only
        if suggestions["descriptions"]:
            st.caption(f"💡 常用描述: {', '.join(suggestions['descriptions'][:3])}")

        # Notes (optional)
        notes = st.text_area(
            "備註 (選填) 📄",
            placeholder="其他備註資訊...",
            height=60,
            help="可選的備註資訊",
            key=f"add_notes_{gen}",
        )

        # Submit button
        submitted = st.form_submit_button(
            "💾 儲存支出",
            use_container_width=True,
            type="primary"
        )

    if not submitted:
        return False

    description = (description or "").strip()
    notes = (notes or "").strip()

    # Validate required fields (values stay in the widgets on failure)
    if not description:
        st.error("請填寫支出描述")
        return False

    if fx_state is not None:
        fx_error = _fx_validation_error(fx_state)
        if fx_error:
            st.error(fx_error)
            return False
    if amount is None or amount <= 0:
        st.error("請填寫有效的金額")
        return False

    if account == "請選擇帳戶...":
        st.error("請選擇記帳帳戶")
        return False

    currency = fx_state.currency if fx_state is not None else ""
    orig_amount_str = str(fx_state.orig_amount) if fx_state is not None else ""
    fx_rate_str = str(fx_state.rate_eff) if fx_state is not None else ""

    # Duplicate-submission guard: the signature of the last SUCCESSFUL write
    # persists across runs; an identical payload within the window is refused.
    # orig_amount is part of it so two SGD amounts rounding to the same NT$
    # are not mistaken for a double tap.
    signature = (expense_date.isoformat(), account, description, float(amount),
                 currency, orig_amount_str)
    last = st.session_state.get("last_expense_submit")
    if last and last[0] == signature and (time.time() - last[1]) < DUPLICATE_SUBMIT_WINDOW:
        st.warning("⚠️ 相同的支出剛剛已儲存，請勿重複提交")
        return False

    # Prepare expense data
    expense_data = {
        "date": expense_date.strftime("%Y-%m-%d"),
        "type_1": type_1,
        "category_type": category_type,
        "amount": amount,
        "account": account,
        "description": description,
        "country": country,
        "location": location,
        "notes": notes,
        # '' for TWD-native rows: the API keeps 幣別/原幣金額/匯率 blank
        "currency": currency,
        "orig_amount": orig_amount_str,
        "fx_rate": fx_rate_str,
    }

    success = api.add_expense(expense_data)

    if success:
        st.session_state["last_expense_submit"] = (signature, time.time())
        if fx_state is not None:
            flash_msg = (f"✅ 成功新增支出: {description} - "
                         f"{fmt_orig(currency, fx_state.orig_amount)} ≈ NT${amount:,.0f}")
        else:
            flash_msg = f"✅ 成功新增支出: {description} - NT${amount:,.0f}"
        st.session_state["add_expense_flash"] = flash_msg
        dropped = _write_warnings(api)
        if dropped:
            st.session_state["add_expense_warnings"] = [FX_DROPPED_WARNING] + dropped
        st.session_state["add_form_gen"] = gen + 1  # reset in-form fields on the next run
        st.cache_data.clear()
        st.rerun()
        return True

    st.error("❌ 新增失敗，請稍後再試")
    return False


def _bump_edit_generation() -> None:
    """
    Invalidate every edit widget. Sheet row numbers are re-used after a
    delete (rows below shift up) and after a relocated update, so widget
    state keyed by row alone would carry over to the NEXT record. Bumping
    the generation gives all edit widgets fresh keys.
    """
    st.session_state["edit_form_gen"] = st.session_state.get("edit_form_gen", 0) + 1
    st.session_state["_edit_last_row"] = None
    _clear_edit_snapshots()


def _clear_edit_snapshots(keep_row: Optional[int] = None) -> None:
    for key in [k for k in st.session_state.keys() if str(k).startswith("edit_orig_")]:
        if keep_row is not None and key == f"edit_orig_{keep_row}":
            continue
        del st.session_state[key]


def _record_label(row) -> str:
    date_str = row['date'].strftime('%m/%d') if pd.notna(row['date']) else 'N/A'
    full_desc = _text(row.get('description', ''))
    desc = full_desc[:20] + ('...' if len(full_desc) > 20 else '')
    amount = parse_amount(row.get('amount'))
    amount_str = f"NT${amount:,.0f}" if amount is not None else "NT$?"
    fx_suffix = ""
    currency = _text(row.get('currency', '')).upper()
    if currency and currency != "TWD":
        orig_label = fmt_orig(currency, _fx_float(row.get('orig_amount')))
        fx_suffix = f" · {orig_label}" if orig_label else f" · {currency}"
    return f"{date_str} - {desc} - {amount_str}{fx_suffix} (#row {int(row['sheet_row'])})"


def edit_expense_form(df: pd.DataFrame) -> bool:
    """
    Form for editing existing expenses. Record identity is the Google Sheet
    row number ('sheet_row'), never the dropdown label or a positional index.
    """
    st.subheader("✏️ 編輯支出")

    # Add refresh button
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔄 重新整理資料"):
            from sheets_api import refresh_data
            _bump_edit_generation()
            refresh_data()
            st.rerun()

    flash = st.session_state.pop("edit_expense_flash", None)
    if flash:
        st.success(flash)
    for warn in st.session_state.pop("edit_expense_warnings", None) or []:
        st.warning(warn)

    if df.empty:
        st.info("📊 目前沒有支出資料可編輯")
        return False

    if 'sheet_row' not in df.columns:
        st.error("❌ 資料缺少工作表列號 (sheet_row)，無法安全編輯，請重新整理資料")
        return False

    # Check API availability
    api = get_sheets_api()
    status = api.get_status()

    if not status["api_available"]:
        st.warning("⚠️ 目前僅支援查看模式，無法編輯支出")
        return False

    # Sort by date (newest first) for easier editing; unparseable dates last
    df_sorted = df.sort_values('date', ascending=False, na_position='last')
    recent_records = df_sorted.head(50)  # Show last 50 expenses for dropdown

    labels: Dict[int, str] = {}
    for _, row in recent_records.iterrows():
        labels[int(row['sheet_row'])] = _record_label(row)
    row_options = list(labels.keys())

    # Generation counter: bumped after every successful write / refresh so
    # that a re-used sheet row number never inherits stale widget state.
    gen = st.session_state.get("edit_form_gen", 0)
    kp = f"edit_g{gen}"

    # Stable key + stable option values (sheet rows): the selection survives
    # label changes caused by concurrent edits elsewhere.
    selected_row_no = st.selectbox(
        "選擇要編輯的支出記錄：",
        options=row_options,
        index=None,
        format_func=lambda r: labels.get(r, f"#row {r}"),
        placeholder="請選擇記錄...",
        help="選擇一筆要編輯的支出記錄",
        key=f"{kp}_record_select",
    )

    prev_row_no = st.session_state.get("_edit_last_row")
    if selected_row_no is None:
        if prev_row_no is not None and prev_row_no not in row_options:
            st.warning("⚠️ 先前選擇的記錄已被修改或刪除，請重新選擇")
        st.session_state["_edit_last_row"] = None
        _clear_edit_snapshots()
        return False

    sheet_row = int(selected_row_no)
    if prev_row_no != sheet_row:
        _clear_edit_snapshots(keep_row=sheet_row)
    st.session_state["_edit_last_row"] = sheet_row

    matches = recent_records[recent_records['sheet_row'] == sheet_row]
    if matches.empty:
        st.warning("⚠️ 所選記錄已不存在，請重新整理後再選擇")
        return False
    selected_row = matches.iloc[0]

    # Snapshot of the record as first shown to the user; used for
    # verification by the API so a concurrent change is detected, not overwritten.
    snapshot_key = f"edit_orig_g{gen}_{sheet_row}"
    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = {
            "sheet_row": sheet_row,
            "date": selected_row['date'].to_pydatetime() if pd.notna(selected_row['date']) else None,
            "description": _text(selected_row.get('description', '')),
            "amount": parse_amount(selected_row.get('amount')),
            "type_1": _text(selected_row.get('type_1', '')),
            "category_type": _text(selected_row.get('category_type', '')),
            "account": _text(selected_row.get('account', '')),
            "country": _text(selected_row.get('country', '')),
            "location": _text(selected_row.get('location', '')),
            "notes": _text(selected_row.get('notes', '')),
            # FX cells ('' / None = TWD-native; a legacy frame has no such columns)
            "currency": _sheet_currency(selected_row.get('currency', '')),
            "orig_amount": _fx_float(selected_row.get('orig_amount')),
            "fx_rate": _fx_float(selected_row.get('fx_rate')),
        }
    original = st.session_state[snapshot_key]

    st.divider()

    # Show current values and allow editing
    st.subheader(f"編輯支出：{original['description'] or 'N/A'} (#row {sheet_row})")

    # 國家 / 地點 outside the form so the location list follows the country
    st.caption("📍 地點資訊")
    country, location = _country_location_selectors(
        f"{kp}_{sheet_row}", original['country'], original['location']
    )

    orig_amount = original['amount']
    date_is_nat = original['date'] is None

    # 💱 FX card (outside the form). Default 幣別 = stored currency regardless of
    # 國家 (G4); a legacy row opens exactly as before unless the user opts in.
    stored_currency = original.get('currency', '') or ''
    fx_optin = st.checkbox(
        "💱 以外幣輸入",
        value=bool(stored_currency),
        key=f"{kp}_fx_optin_{sheet_row}",
        help="以原幣金額 × 匯率 計算台幣金額",
    )
    fx_state = None
    if fx_optin:
        stored_fx = FxStored(stored_currency, original.get('orig_amount'),
                             original.get('fx_rate'), orig_amount)
        fx_state = _fx_block(
            kp, country, sheet_row, stored=stored_fx,
            on_date=original['date'].date() if not date_is_nat else today_local(),
            show_statement=True, df=df,
        )

    # Every widget key includes the sheet row: switching records never
    # carries stale, unsubmitted edits over.
    with st.form(f"{kp}_expense_form_{sheet_row}"):
        col1, col2 = st.columns(2)

        with col1:
            if date_is_nat:
                st.warning("⚠️ 此記錄的原始日期無法解析，請手動選擇正確日期")
            new_date = st.date_input(
                "日期",
                value=None if date_is_nat else original['date'].date(),
                key=f"{kp}_date_{sheet_row}",
            )

        with col2:
            account_options, account_index = _options_with(ACCOUNTS, original['account'])
            new_account = st.selectbox(
                "帳戶",
                options=account_options,
                index=account_index,
                format_func=_fmt_blank,
                key=f"{kp}_account_{sheet_row}",
            )

        # Type_1 selection (Daily vs Travel)
        type_1_options, type_1_index = _options_with(TYPE_1_OPTIONS, original['type_1'])
        new_type_1 = st.selectbox(
            "類型",
            options=type_1_options,
            index=type_1_index,
            format_func=_fmt_blank,
            key=f"{kp}_type_1_{sheet_row}",
        )

        # Category selection (Type_2)
        category_options, category_index = _options_with(CATEGORIES, original['category_type'])
        new_category_type = st.selectbox(
            "分類",
            options=category_options,
            index=category_index,
            format_func=_fmt_blank,
            key=f"{kp}_category_{sheet_row}",
        )

        if fx_state is not None:
            # 金額 is derived from the card: shown, never typed (rules i-iii)
            _fx_amount_info(fx_state)
            new_amount = fx_state.twd
        else:
            if orig_amount is None:
                st.warning(f"⚠️ 此記錄的原始金額無法解析（{_text(selected_row.get('amount'))!r}），更新前請輸入新金額")
            # Negative stored amounts (refunds) must not crash the widget
            amount_min = None if (orig_amount is not None and orig_amount < 0) else 0.0
            new_amount = st.number_input(
                "金額",
                min_value=amount_min,
                step=10.0,
                value=float(orig_amount) if orig_amount is not None else None,
                placeholder="請輸入金額...",
                format="%.0f",
                key=f"{kp}_amount_{sheet_row}",
            )

        new_description = st.text_input(
            "描述",
            value=original['description'],
            key=f"{kp}_description_{sheet_row}",
        )

        new_notes = st.text_input(
            "備註 (選填)",
            value=original['notes'],
            key=f"{kp}_notes_{sheet_row}",
        )

        confirm_delete = st.checkbox(
            "我確認要刪除這筆記錄",
            key=f"{kp}_confirm_delete_{sheet_row}",
        )

        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            update_clicked = st.form_submit_button(
                "💾 更新",
                use_container_width=True,
                type="primary",
            )
        with btn_col2:
            delete_clicked = st.form_submit_button(
                "🗑️ 刪除",
                use_container_width=True,
                type="secondary",
            )

    if update_clicked:
        new_description = (new_description or "").strip()
        new_notes = (new_notes or "").strip()

        if new_date is None:
            st.error("此記錄原始日期無法解析，請先選擇日期")
            return False
        if not new_description:
            st.error("請填寫支出描述")
            return False
        if fx_state is not None:
            fx_error = _fx_validation_error(fx_state)
            if fx_error:
                st.error(fx_error)
                return False
        else:
            if new_amount is None:
                st.error("請填寫金額")
                return False
            if orig_amount is None and new_amount <= 0:
                st.error("原始金額無法解析，請輸入大於 0 的新金額")
                return False
            if new_amount == 0:
                st.error("金額不可為 0")
                return False
            if new_amount < 0 and not (orig_amount is not None and orig_amount < 0):
                st.error("金額必須大於 0（僅退款記錄可為負數）")
                return False

        # FX cells (plan §2.5): whenever the card is shown, updated_data ALWAYS
        # carries the three FX keys and 金額 = the value the card displays
        # (rules i-iii already folded into fx_state.twd / rate_eff), so the
        # saved 金額 can never differ from the in-form NT$ preview and a
        # stale (orig, rate) can never sit beside a new 金額 -- this is also
        # what lets the §2.6 audit's "換算不一致" rows be repaired by a plain
        # 更新. (iv) 幣別 -> TWD (card hidden / opt-out) on a converted row
        # writes explicit blanks; a legacy row without the card carries no
        # FX keys and the API preserves the cells.
        fx_fields: Dict[str, str] = {}
        if fx_state is not None:
            amount_out = float(fx_state.twd)
            fx_fields = {
                "currency": fx_state.currency,
                "orig_amount": str(fx_state.orig_amount),
                "fx_rate": str(fx_state.rate_eff),
            }
        else:
            amount_out = float(new_amount)
            if stored_currency:
                fx_fields = {"currency": "", "orig_amount": "", "fx_rate": ""}

        # Prepare updated data. Columns the user did not change among
        # country/location/notes are omitted so the API preserves the live
        # sheet values instead of a cached snapshot.
        updated_data = {
            "date": new_date.strftime("%Y-%m-%d"),
            "type_1": new_type_1,
            "category_type": new_category_type,
            "amount": amount_out,
            "account": new_account,
            "description": new_description,
        }
        updated_data.update(fx_fields)
        if country != original['country']:
            updated_data["country"] = country
        if location != original['location']:
            updated_data["location"] = location
        if new_notes != original['notes']:
            updated_data["notes"] = new_notes

        success = api.update_expense(sheet_row, original, updated_data)
        if success:
            if fx_state is not None:
                flash_msg = (f"✅ 已更新支出：{new_description} "
                             f"({fmt_orig(fx_state.currency, fx_state.orig_amount)} ≈ NT${amount_out:,.0f})")
            else:
                flash_msg = f"✅ 已更新支出：{new_description} (NT${amount_out:,.0f})"
            st.session_state["edit_expense_flash"] = flash_msg
            dropped = _write_warnings(api)
            if dropped:
                st.session_state["edit_expense_warnings"] = [FX_DROPPED_WARNING] + dropped
            _bump_edit_generation()
            st.cache_data.clear()
            st.rerun()
            return True

        st.error(f"❌ 更新失敗：{new_description}")
        st.info("💡 請檢查網路連線，或按「重新整理資料」後重試")
        return False

    if delete_clicked:
        desc = original['description'] or 'N/A'
        amount_str = f"NT${orig_amount:,.0f}" if orig_amount is not None else "NT$?"
        date_str = original['date'].strftime('%Y/%m/%d') if original['date'] is not None else 'N/A'

        if not confirm_delete:
            st.error("請先勾選「我確認要刪除這筆記錄」再按刪除")
            return False

        success = api.delete_expense(sheet_row, original)
        if success:
            st.session_state["edit_expense_flash"] = f"✅ 已刪除支出：{desc} ({amount_str}) - {date_str}"
            _bump_edit_generation()
            st.cache_data.clear()
            st.rerun()
            return True

        st.error(f"❌ 刪除失敗：{desc}")
        with st.expander("🔍 除錯資訊", expanded=False):
            st.write(f"工作表列號: {sheet_row}")
            st.write(f"描述: {desc}")
            st.write(f"金額: {amount_str}")
            st.write(f"日期: {date_str}")
            st.write("請檢查是否該記錄已被其他人修改或刪除，或重新整理頁面後重試")
        return False

    return False
