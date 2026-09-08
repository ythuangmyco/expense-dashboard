"""
Shared, dependency-free helpers (no Streamlit imports) used by
sheets_api.py, input_forms.py and app.py.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from zoneinfo import ZoneInfo

# The family lives in Taiwan; the server (Streamlit Cloud) runs in UTC.
LOCAL_TZ = ZoneInfo("Asia/Taipei")


def now_local() -> datetime:
    """Current wall-clock time in Taiwan (tz-aware)."""
    return datetime.now(LOCAL_TZ)


def today_local() -> date:
    """Today's date in Taiwan."""
    return now_local().date()


def parse_amount(value):
    """
    Parse an amount cell as it may come back from Google Sheets or CSV:
    '26,495.00', 'NT$1,200', ' 240 ', 1200, 1200.0, '', None, 'nan'.
    Returns float, or None when the value cannot be interpreted as a number.
    Never raises.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value != value:  # NaN
            return None
        return float(value)
    text = str(value).strip()
    if text == "" or text.lower() in ("nan", "none", "null"):
        return None
    for token in ("NT$", "TWD", "$", ",", "\"", "'", " "):
        text = text.replace(token, "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    if number != number:
        return None
    return -number if negative else number


# ---------------------------------------------------------------------------
# Foreign-currency arithmetic and formatting (PLAN_fx_and_overview.md §2.4/§4)
# ---------------------------------------------------------------------------
_RATE_QUANT = Decimal("0.000001")   # 匯率 always 6 dp (RATE_DECIMALS)
_ONE = Decimal(1)


def _dec(value) -> Decimal:
    """
    Decimal from any numeric-ish input via ``Decimal(str(value))`` (G2).
    Decimal(12.5)*Decimal(23.4) is 292.4999…; Decimal("12.5")*Decimal("23.4")
    is exactly 292.5. Raises ValueError for None / NaN / non-numeric text.
    """
    if value is None or isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, Decimal):
        d = value
    else:
        if isinstance(value, float) and value != value:
            raise ValueError("not a number: nan")
        try:
            d = Decimal(str(value).strip().replace(",", ""))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"not a number: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"not a number: {value!r}")
    return d


def q6(x) -> Decimal:
    """Quantize a rate to 6 decimal places, ROUND_HALF_UP."""
    return _dec(x).quantize(_RATE_QUANT, rounding=ROUND_HALF_UP)


def to_twd(orig, rate, orig_dp: int = 2) -> int:
    """
    Integer TWD from an original-currency amount and a TWD-per-unit rate.

    orig is first quantized to ``orig_dp`` decimals, rate to 6 dp, and the
    product is rounded HALF_UP to a whole NT$ — the same arithmetic the sheet
    invariant ``金額 == to_twd(原幣金額, 匯率)`` is audited with.
    to_twd(12.5, 23.4) == 293; to_twd(200000, 0.205065, 0) == 41013.
    Raises ValueError on None/NaN inputs or a negative orig_dp.
    """
    if orig_dp < 0:
        raise ValueError("orig_dp must be >= 0")
    o = _dec(orig).quantize(_ONE.scaleb(-orig_dp), rounding=ROUND_HALF_UP)
    r = q6(rate)
    return int((o * r).quantize(_ONE, rounding=ROUND_HALF_UP))


def fmt_orig(currency: str, value) -> str:
    """
    Original-currency label: fmt_orig("SGD", 12.5) -> "SGD 12.50",
    fmt_orig("JPY", 200000) -> "JPY 200,000". Decimals come from
    config.CURRENCY_META (2 when the currency is unknown).
    Returns "" when the value is not a number.
    """
    from config import CURRENCY_META  # local import keeps helpers config-light
    code = (currency or "").strip().upper()
    try:
        d = _dec(value)
    except ValueError:
        return ""
    decimals = CURRENCY_META.get(code, (2, 0.01))[0]
    d = d.quantize(_ONE.scaleb(-decimals), rounding=ROUND_HALF_UP)
    return f"{code} {d:,.{decimals}f}".strip()


def fmt_twd(n) -> str:
    """
    Whole-NT$ label: fmt_twd(1234.4) -> "NT$1,234"; negative -> "-NT$1,234"
    (ASCII minus so st.metric colours the delta). Non-numbers -> "—".
    """
    try:
        d = _dec(n).quantize(_ONE, rounding=ROUND_HALF_UP)
    except ValueError:
        return "—"
    sign = "-" if d < 0 else ""
    return f"{sign}NT${abs(int(d)):,}"


def fmt_pct(x, decimals: int = 0) -> str:
    """
    Signed percentage from a ratio: fmt_pct(-0.123) -> "-12%",
    fmt_pct(0.05) -> "+5%", fmt_pct(0) -> "0%". Non-numbers -> "—".
    """
    try:
        d = (_dec(x) * 100).quantize(_ONE.scaleb(-decimals), rounding=ROUND_HALF_UP)
    except ValueError:
        return "—"
    if d == 0:
        d = abs(d)  # never "-0%"
    sign = "+" if d > 0 else ("-" if d < 0 else "")
    return f"{sign}{abs(d):.{decimals}f}%"


def week_bounds(d: date) -> tuple:
    """(Monday, Sunday) of the ISO week containing ``d``."""
    if isinstance(d, datetime):
        d = d.date()
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)
