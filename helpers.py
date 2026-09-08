"""
Shared, dependency-free helpers (no Streamlit imports) used by
sheets_api.py, input_forms.py and app.py.
"""

from datetime import datetime, date
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
