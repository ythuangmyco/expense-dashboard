"""
總覽 pure logic (PLAN_fx_and_overview.md §3, §5 steps 6-8).

Pure pandas / stdlib — NO streamlit import, so every function is unit-testable
and cacheable by the caller. All money values are integer TWD derived from
``amount`` via ``pd.to_numeric(errors="coerce")`` with NaN rows *dropped*
(never coerced to 0). Every function tolerates:

* a legacy frame lacking ``currency`` / ``orig_amount`` / ``fx_rate``
  (a ``last_good_df`` captured before the FX deploy — G15),
* an empty frame (even ``pd.DataFrame()`` with no columns),
* NaT dates and NaN amounts.

Public API (the contract the UI codes against)
----------------------------------------------
resolve_period(label, today, df=None, custom=None)     -> (start, end) | (None, None)
comparison_window(label, start, end)                   -> (cstart, cend, comp_label) | (None, None, None)
apply_filters(df, filters)                             -> df
canonical_category(value)                              -> str
slice_period(df, start, end)                           -> df
period_summary(df, start, end, filters=None)           -> dict (see docstring)
daily_series(df, start, end)                           -> DataFrame[date, total]
cumulative_series(df, start, end)                      -> DataFrame[day_index, total, cumulative]
monthly_series(df)                                     -> DataFrame[month, total, count]
detect_trips(df, today)                                -> list[Trip]
active_trip(trips, today)                              -> Trip | None
trip_label(trip)                                       -> str
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

from config import (
    CATEGORY_ALIASES,
    COMPARISON_LABEL,
    COUNTRY_FLAG,
    CURRENCY_META,
    TRIP_ACTIVE_GRACE_DAYS,
    TRIP_GAP_DAYS,
    TRIP_PREBOOK_WINDOW_DAYS,
)
from helpers import to_twd, today_local, week_bounds

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRAVEL_TYPE = "✈️ 旅行"
DAILY_TYPE = "📅 日常"
HOME_COUNTRIES = ("", "台灣")
PREBOOK_PENDING = "行前 · 尚未出發"      # Trip.country of the pseudo-entry (never a 台灣 trip)
PREBOOK_PENDING_FLAG = "🧳"

CUSTOM_LABEL = "自訂範圍"
ALL_LABEL = "全部"
TRIP_LABEL = "旅行"
PRESET_LABELS = ("今天", "本週", "本月", "本年", "上月", "最近7天", "最近30天", ALL_LABEL, CUSTOM_LABEL)

_TEXT_COLS = ("type_1", "category_type", "account", "description", "country", "location", "notes", "currency")
_NUM_COLS = ("amount", "orig_amount", "fx_rate")
_ONE = Decimal(1)


# ---------------------------------------------------------------------------
# Frame normalisation
# ---------------------------------------------------------------------------

def _as_date(value) -> Optional[date]:
    """date / datetime / Timestamp / str -> date; None / NaT -> None."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _prepare(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Copy of ``df`` with every column the overview needs present and typed:
    ``date`` datetime64 (normalised to midnight), numeric columns float64
    (unparseable -> NaN), text columns str ('' for missing / 'nan'),
    ``sheet_row`` Int64. Never mutates the caller's frame.
    """
    if df is None:
        df = pd.DataFrame()
    out = df.copy()
    n = len(out)
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    else:
        out["date"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[ns]")
    for col in _NUM_COLS:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
        else:
            out[col] = pd.Series(float("nan"), index=out.index, dtype="float64")
    for col in _TEXT_COLS:
        if col in out.columns:
            out[col] = out[col].map(_clean_text)
        else:
            out[col] = pd.Series([""] * n, index=out.index, dtype="object")
    out["currency"] = out["currency"].str.upper().replace({"TWD": ""})
    if "sheet_row" in out.columns:
        out["sheet_row"] = pd.to_numeric(out["sheet_row"], errors="coerce").astype("Int64")
    else:
        out["sheet_row"] = pd.Series([pd.NA] * n, index=out.index, dtype="Int64")
    return out


def _clean_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    text = str(value).strip()
    return "" if text.lower() in ("nan", "none", "null") else text


def _int_twd(value) -> int:
    """Float/Decimal -> whole NT$ (HALF_UP). NaN/None -> 0."""
    if value is None:
        return 0
    try:
        d = Decimal(str(value))
    except Exception:
        return 0
    if not d.is_finite():
        return 0
    return int(d.quantize(_ONE, rounding=ROUND_HALF_UP))


def _valid_amounts(frame: pd.DataFrame) -> pd.Series:
    """The ``amount`` column with NaN rows dropped (never coerced to 0)."""
    return frame["amount"].dropna()


def _sum_twd(frame: pd.DataFrame) -> int:
    return _int_twd(float(_valid_amounts(frame).sum())) if len(frame) else 0


def _sheet_rows(frame: pd.DataFrame) -> List[int]:
    return sorted(int(v) for v in frame["sheet_row"].dropna().tolist())


# ---------------------------------------------------------------------------
# Period resolution
# ---------------------------------------------------------------------------

def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def _prev_month_start(d: date) -> date:
    return _month_start(_month_start(d) - timedelta(days=1))


def resolve_period(label: str, today: date, df: Optional[pd.DataFrame] = None,
                   custom: Optional[Tuple[date, date]] = None) -> Tuple[Optional[date], Optional[date]]:
    """
    (start, end) — inclusive calendar dates — for a period label, or (None, None).

    今天 · 本週 (Mon..today) · 本月 · 本年 · 上月 (full) · 最近7天 / 最近30天
    (N calendar days ending today) · 全部 (df date min..max; today..today when
    df is None/empty/all-NaT) · 自訂範圍 (``custom``; (None, None) when custom
    is None or end < start). Unknown labels -> (None, None).
    """
    today = _as_date(today)
    if today is None or label is None:
        return None, None
    label = str(label).strip()
    if label == "今天":
        return today, today
    if label == "本週":
        monday, _ = week_bounds(today)
        return monday, today
    if label == "本月":
        return _month_start(today), today
    if label == "本年":
        return today.replace(month=1, day=1), today
    if label == "上月":
        pstart = _prev_month_start(today)
        return pstart, _month_end(pstart)
    if label == "最近7天":
        return today - timedelta(days=6), today
    if label == "最近30天":
        return today - timedelta(days=29), today
    if label == ALL_LABEL:
        if df is not None and len(df) and "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce").dropna()
            if len(dates):
                return dates.min().date(), dates.max().date()
        return today, today
    if label == CUSTOM_LABEL:
        if not custom or len(custom) != 2:
            return None, None
        start, end = _as_date(custom[0]), _as_date(custom[1])
        if start is None or end is None or end < start:
            return None, None
        return start, end
    return None, None


def _same_day_prev_year(d: date) -> date:
    if d.month == 2 and d.day == 29:
        return date(d.year - 1, 2, 28)
    return date(d.year - 1, d.month, d.day)


def comparison_window(label: str, start: Optional[date], end: Optional[date]
                      ) -> Tuple[Optional[date], Optional[date], Optional[str]]:
    """
    (cstart, cend, comp_label) for the window a period is compared against,
    per config.COMPARISON_LABEL semantics:

    今天 -> 昨天; 本週 -> 上週同期 (Mon..same weekday); 本月 -> 上月同期
    (day 1..same day, clamped to the shorter month); 上月 -> 前一個月 (full);
    本年 -> 去年同期 (Jan 1..same M/D, Feb 29 -> Feb 28); 最近7天 / 最近30天 /
    自訂範圍 -> the preceding window of equal length; 全部 / 旅行 / unknown ->
    (None, None, None).
    """
    start, end = _as_date(start), _as_date(end)
    if start is None or end is None or end < start:
        return None, None, None
    label = str(label).strip() if label is not None else ""
    comp_label = COMPARISON_LABEL.get(label)
    if comp_label is None:
        return None, None, None
    if label == "今天":
        return start - timedelta(days=1), end - timedelta(days=1), comp_label
    if label == "本週":
        return start - timedelta(days=7), end - timedelta(days=7), comp_label
    if label == "本月":
        pstart = _prev_month_start(start)
        pend = pstart.replace(day=min(end.day, calendar.monthrange(pstart.year, pstart.month)[1]))
        return pstart, pend, comp_label
    if label == "上月":
        pstart = _prev_month_start(start)
        return pstart, _month_end(pstart), comp_label
    if label == "本年":
        return date(start.year - 1, 1, 1), _same_day_prev_year(end), comp_label
    # 最近7天 / 最近30天 / 自訂範圍 (and any other labelled preset): preceding equal-length window
    n = (end - start).days + 1
    return start - timedelta(days=n), start - timedelta(days=1), comp_label


# ---------------------------------------------------------------------------
# Filters / categories / slicing
# ---------------------------------------------------------------------------

def canonical_category(value) -> str:
    """Display/grouping-time alias merge (📱通信 -> 📱 通信); raw values are never rewritten."""
    text = _clean_text(value)
    return CATEGORY_ALIASES.get(text, text)


def _as_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def apply_filters(df: pd.DataFrame, filters: Optional[Dict[str, Any]]) -> pd.DataFrame:
    """
    Row filter. ``filters`` keys (all optional; an empty list means no filter,
    there is no 全部 sentinel): ``accounts``, ``type_1``, ``categories``
    (compared on canonical_category()), ``countries``. Keys starting with ``_``
    are ignored (``_label`` / ``_today`` are period_summary hints).
    Returns a normalised copy (see _prepare) even when no filter applies.
    """
    out = _prepare(df)
    if not filters:
        return out
    accounts = _as_list(filters.get("accounts"))
    if accounts:
        out = out[out["account"].isin(accounts)]
    types = _as_list(filters.get("type_1"))
    if types:
        out = out[out["type_1"].isin(types)]
    categories = [canonical_category(c) for c in _as_list(filters.get("categories"))]
    if categories:
        out = out[out["category_type"].map(canonical_category).isin(categories)]
    countries = _as_list(filters.get("countries"))
    if countries:
        out = out[out["country"].isin(countries)]
    return out


def slice_period(df: pd.DataFrame, start: Optional[date], end: Optional[date]) -> pd.DataFrame:
    """Rows with start <= date <= end (inclusive); NaT dropped. None bounds -> empty frame."""
    out = _prepare(df)
    start, end = _as_date(start), _as_date(end)
    if start is None or end is None or end < start:
        return out.iloc[0:0]
    dates = out["date"]
    mask = dates.notna() & (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
    return out[mask]


# ---------------------------------------------------------------------------
# Period summary
# ---------------------------------------------------------------------------

def _row_ref(row) -> Dict[str, Any]:
    d = _as_date(row["date"])
    amt = row["amount"]
    return {
        "date": d,
        "description": row["description"],
        "amount": None if pd.isna(amt) else _int_twd(amt),
        "sheet_row": None if pd.isna(row["sheet_row"]) else int(row["sheet_row"]),
    }


def _is_inconsistent(row) -> bool:
    """A converted row whose 金額 is > 1 TWD away from to_twd(orig, rate) (or cannot be verified)."""
    try:
        decimals = CURRENCY_META.get(row["currency"], (2, 0.01))[0]
        expected = to_twd(row["orig_amount"], row["fx_rate"], decimals)
    except (ValueError, TypeError):
        return True
    amt = row["amount"]
    if pd.isna(amt):
        return True
    return abs(float(amt) - expected) > 1


def _fx_by_currency(frame: pd.DataFrame) -> Dict[str, Decimal]:
    """Sum of orig_amount per non-blank currency, as Decimal quantised to the currency's decimals."""
    out: Dict[str, Decimal] = {}
    conv = frame[(frame["currency"] != "") & frame["orig_amount"].notna()]
    for ccy, sub in conv.groupby("currency", sort=True):
        total = sum((Decimal(str(v)) for v in sub["orig_amount"].tolist()), Decimal(0))
        decimals = CURRENCY_META.get(ccy, (2, 0.01))[0]
        out[str(ccy)] = total.quantize(_ONE.scaleb(-decimals), rounding=ROUND_HALF_UP)
    return out


def period_summary(df: pd.DataFrame, start: Optional[date], end: Optional[date],
                   filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Everything screen 1 of 總覽 needs, computed once on the filtered period slice.

    ``filters`` accepts the apply_filters keys plus two hints: ``_label`` (the
    period label; ``projected_month_end`` is only computed for 本月) and
    ``_today`` (date; defaults to helpers.today_local()).

    Keys:
      total:int                     TWD sum of parseable amounts in the slice
      count:int                     rows in the slice (incl. unparseable amounts)
      days:int                      calendar days in the window (incl. today's partial)
      daily_avg:float               total / days
      projected_month_end:int|None  本月 only: daily_avg × days in the month
      today_total:int, today_count:int   rows dated _today on the FILTERED frame
                                    (independent of the period — the 今天 tile is always today)
      by_account:dict[str,int]      desc by total
      by_type1:dict[str,int]        📅 日常 and ✈️ 旅行 always present (0 when absent) + any other value seen
      top_categories:list[(canonical_category, total:int, share:float)]  desc; caller slices [:3]
      other_categories_count:int, other_categories_total:int   everything beyond the top 3
      fx_by_currency:dict[str,Decimal]   sum of orig_amount per non-blank currency
      largest:dict|None             {description, amount:int, date:date, sheet_row}
      unparseable_count / zero_count / converted_count / inconsistent_count / unlabeled_currency_count
      unparseable_rows / zero_rows / inconsistent_rows / unlabeled_currency_rows
                                    list[{date, description, amount, sheet_row}] for 🧹 資料檢查
      start:date|None, end:date|None, label:str|None   echo of the inputs
    """
    filters = dict(filters or {})
    label = filters.pop("_label", None)
    today = _as_date(filters.pop("_today", None)) or today_local()
    start, end = _as_date(start), _as_date(end)

    filtered = apply_filters(df, filters)
    sliced = slice_period(filtered, start, end)
    valid = sliced[sliced["amount"].notna()]

    total = _sum_twd(sliced)
    days = (end - start).days + 1 if (start is not None and end is not None and end >= start) else 0
    daily_avg = (total / days) if days else 0.0
    projected = None
    if label == "本月" and days and start is not None:
        projected = _int_twd(daily_avg * calendar.monthrange(start.year, start.month)[1])

    today_rows = filtered[filtered["date"] == pd.Timestamp(today)]

    by_account = {str(k): _int_twd(v) for k, v in valid.groupby("account")["amount"].sum().items()}
    by_account = dict(sorted(by_account.items(), key=lambda kv: (-kv[1], kv[0])))

    by_type1 = {DAILY_TYPE: 0, TRAVEL_TYPE: 0}
    for k, v in valid.groupby("type_1")["amount"].sum().items():
        by_type1[str(k)] = _int_twd(v)

    cats = valid.assign(_cat=valid["category_type"].map(canonical_category)).groupby("_cat")["amount"].sum()
    top = sorted(((str(k), _int_twd(v)) for k, v in cats.items()), key=lambda kv: (-kv[1], kv[0]))
    top_categories = [(k, v, (v / total) if total else 0.0) for k, v in top]
    rest = top_categories[3:]

    largest = None
    if len(valid):
        idx = valid["amount"].idxmax()
        largest = _row_ref(valid.loc[idx])

    unparseable = sliced[sliced["amount"].isna()]
    zero = sliced[sliced["amount"] == 0]
    converted = sliced[sliced["currency"] != ""]
    inconsistent = converted[converted.apply(_is_inconsistent, axis=1)] if len(converted) else converted
    unlabeled = sliced[(~sliced["country"].isin(HOME_COUNTRIES)) & (sliced["currency"] == "")]

    return {
        "total": total,
        "count": int(len(sliced)),
        "days": int(days),
        "daily_avg": float(daily_avg),
        "projected_month_end": projected,
        "today_total": _sum_twd(today_rows),
        "today_count": int(len(today_rows)),
        "by_account": by_account,
        "by_type1": by_type1,
        "top_categories": top_categories,
        "other_categories_count": len(rest),
        "other_categories_total": sum(v for _, v, _ in rest),
        "fx_by_currency": _fx_by_currency(sliced),
        "largest": largest,
        "unparseable_count": int(len(unparseable)),
        "zero_count": int(len(zero)),
        "converted_count": int(len(converted)),
        "inconsistent_count": int(len(inconsistent)),
        "unlabeled_currency_count": int(len(unlabeled)),
        "unparseable_rows": [_row_ref(r) for _, r in unparseable.iterrows()],
        "zero_rows": [_row_ref(r) for _, r in zero.iterrows()],
        "inconsistent_rows": [_row_ref(r) for _, r in inconsistent.iterrows()],
        "unlabeled_currency_rows": [_row_ref(r) for _, r in unlabeled.iterrows()],
        "start": start,
        "end": end,
        "label": label,
    }


# ---------------------------------------------------------------------------
# Series for the hero sparkline / 趨勢 expander
# ---------------------------------------------------------------------------

def daily_series(df: pd.DataFrame, start: Optional[date], end: Optional[date]) -> pd.DataFrame:
    """
    DataFrame[date (datetime64, midnight), total (int64)] over EVERY calendar day
    start..end, zero-filled. Empty frame (same columns) when the bounds are invalid.
    """
    start, end = _as_date(start), _as_date(end)
    if start is None or end is None or end < start:
        return pd.DataFrame({"date": pd.Series(dtype="datetime64[ns]"), "total": pd.Series(dtype="int64")})
    sliced = slice_period(df, start, end)
    valid = sliced[sliced["amount"].notna()]
    per_day = valid.groupby("date")["amount"].sum()
    index = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D")
    totals = per_day.reindex(index, fill_value=0.0)
    return pd.DataFrame({
        "date": index,
        "total": pd.Series([_int_twd(v) for v in totals.tolist()], dtype="int64").values,
    })


def cumulative_series(df: pd.DataFrame, start: Optional[date], end: Optional[date]) -> pd.DataFrame:
    """DataFrame[day_index (1..N), total, cumulative] on a categorical day-of-period axis."""
    daily = daily_series(df, start, end)
    out = pd.DataFrame({
        "day_index": pd.Series(range(1, len(daily) + 1), dtype="int64"),
        "total": daily["total"].astype("int64").values,
    })
    out["cumulative"] = out["total"].cumsum().astype("int64")
    return out


def monthly_series(df: pd.DataFrame) -> pd.DataFrame:
    """
    DataFrame[month ('YYYY-MM'), total (int64), count (int64 rows)] for every month
    between the earliest and latest dated row; months without rows are 0.
    Rows with NaT dates are ignored; NaN amounts count as rows but add 0.
    """
    empty = pd.DataFrame({"month": pd.Series(dtype="object"),
                          "total": pd.Series(dtype="int64"), "count": pd.Series(dtype="int64")})
    frame = _prepare(df)
    dated = frame[frame["date"].notna()]
    if not len(dated):
        return empty
    periods = dated["date"].dt.to_period("M")
    totals = dated["amount"].groupby(periods).sum(min_count=1)
    counts = dated["amount"].groupby(periods).size()
    full = pd.period_range(periods.min(), periods.max(), freq="M")
    totals = totals.reindex(full).fillna(0.0)
    counts = counts.reindex(full, fill_value=0)
    return pd.DataFrame({
        "month": [str(p) for p in full],
        "total": pd.Series([_int_twd(v) for v in totals.tolist()], dtype="int64").values,
        "count": counts.astype("int64").values,
    })


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

@dataclass
class Trip:
    """
    One detected trip.

    total / count cover EVERY row attached to the trip (in-country rows plus the
    行前 rows attached to it); prebook_total / prebook_count are the 行前 subset
    (旅行 rows with 國家=台灣 and same-country short pre-booking clusters);
    in_trip_total / in_trip_count = the in-country remainder. start / end are the
    in-country dates (行前 rows do not widen the range). For the pseudo-entry
    (country == PREBOOK_PENDING) every row is 行前 and start/end span those rows.
    """
    country: str
    start: date
    end: date
    total: int
    count: int
    fx_by_currency: Dict[str, Decimal] = field(default_factory=dict)
    prebook_total: int = 0
    prebook_count: int = 0
    sheet_rows: List[int] = field(default_factory=list)

    @property
    def is_pending(self) -> bool:
        return self.country == PREBOOK_PENDING

    @property
    def in_trip_total(self) -> int:
        return self.total - self.prebook_total

    @property
    def in_trip_count(self) -> int:
        return self.count - self.prebook_count

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def _clusters(frame: pd.DataFrame, gap_days: int) -> List[pd.DataFrame]:
    """Split a date-sorted frame into runs where consecutive rows are <= gap_days apart."""
    if not len(frame):
        return []
    frame = frame.sort_values(["date", "sheet_row"], kind="mergesort")
    dates = frame["date"].tolist()
    groups: List[List[int]] = [[0]]
    for i in range(1, len(dates)):
        if (dates[i] - dates[i - 1]).days > gap_days:
            groups.append([i])
        else:
            groups[-1].append(i)
    return [frame.iloc[g] for g in groups]


class _Cluster:
    __slots__ = ("country", "start", "end", "rows", "prebook")

    def __init__(self, country: str, rows: pd.DataFrame):
        self.country = country
        self.rows = rows
        self.start = _as_date(rows["date"].min())
        self.end = _as_date(rows["date"].max())
        self.prebook: List[pd.DataFrame] = []

    @property
    def span(self) -> int:
        return (self.end - self.start).days + 1

    def build(self) -> Trip:
        pre = pd.concat(self.prebook) if self.prebook else self.rows.iloc[0:0]
        all_rows = pd.concat([self.rows, pre]) if len(pre) else self.rows
        return Trip(
            country=self.country,
            start=self.start,
            end=self.end,
            total=_sum_twd(all_rows),
            count=int(len(all_rows)),
            fx_by_currency=_fx_by_currency(all_rows),
            prebook_total=_sum_twd(pre),
            prebook_count=int(len(pre)),
            sheet_rows=_sheet_rows(all_rows),
        )


def detect_trips(df: pd.DataFrame, today: Optional[date] = None) -> List[Trip]:
    """
    Trips from ✈️ 旅行 rows, newest first (start desc, then end desc).

    1. Rows with type_1 == ✈️ 旅行 and country not in ('', '台灣') are grouped by
       country and split on gaps > TRIP_GAP_DAYS between consecutive rows.
    2. A same-country cluster spanning <= TRIP_GAP_DAYS calendar days whose next
       same-country cluster starts within TRIP_PREBOOK_WINDOW_DAYS is a
       pre-booking (flight / rail / insurance bought at home but filed under
       the destination) and is attached to that trip as 行前.
    3. 旅行 rows with 國家 = 台灣 attach as 行前 to the trip whose
       [start, end + TRIP_GAP_DAYS] contains the row date (airport spend on the
       travel days), else to the NEXT trip (any country) starting within
       TRIP_PREBOOK_WINDOW_DAYS; rows with no such trip form pseudo-entries
       with country == PREBOOK_PENDING ('行前 · 尚未出發'), one per gap-split
       run. A 台灣 trip is never produced.
    ``today`` is accepted for API symmetry with active_trip (not needed by the rules).
    """
    frame = _prepare(df)
    travel = frame[(frame["type_1"] == TRAVEL_TYPE) & frame["date"].notna()]
    if not len(travel):
        return []
    travel = travel.sort_values(["date", "sheet_row"], kind="mergesort")
    foreign = travel[~travel["country"].isin(HOME_COUNTRIES)]
    home = travel[travel["country"].isin(HOME_COUNTRIES)]

    # 1. per-country gap clusters
    clusters: List[_Cluster] = []
    for country, sub in foreign.groupby("country", sort=False):
        clusters.extend(_Cluster(str(country), rows) for rows in _clusters(sub, TRIP_GAP_DAYS))

    # 2. same-country short clusters preceding a trip within the window -> 行前
    trips: List[_Cluster] = []
    by_country: Dict[str, List[_Cluster]] = {}
    for c in clusters:
        by_country.setdefault(c.country, []).append(c)
    for country, runs in by_country.items():
        runs.sort(key=lambda c: (c.start, c.end))
        target: Optional[_Cluster] = None
        for c in reversed(runs):
            if (target is not None and c.span <= TRIP_GAP_DAYS
                    and (target.start - c.end).days <= TRIP_PREBOOK_WINDOW_DAYS):
                target.prebook.append(c.rows)
            else:
                trips.append(c)
                target = c

    # 3. 台灣 rows -> containing trip, else next trip within the window, else pending
    trips.sort(key=lambda c: (c.start, c.end))
    orphan_idx: List[int] = []
    grace = timedelta(days=TRIP_GAP_DAYS)
    window = timedelta(days=TRIP_PREBOOK_WINDOW_DAYS)
    for pos, (idx, row) in enumerate(home.iterrows()):
        d = _as_date(row["date"])
        holder = next((t for t in trips if t.start <= d <= t.end + grace), None)
        if holder is None:
            holder = next((t for t in trips if t.start >= d and (t.start - d) <= window), None)
        if holder is None:
            orphan_idx.append(pos)
        else:
            holder.prebook.append(home.iloc[[pos]])

    result = [c.build() for c in trips]
    if orphan_idx:
        for rows in _clusters(home.iloc[orphan_idx], TRIP_GAP_DAYS):
            result.append(Trip(
                country=PREBOOK_PENDING,
                start=_as_date(rows["date"].min()),
                end=_as_date(rows["date"].max()),
                total=_sum_twd(rows),
                count=int(len(rows)),
                fx_by_currency=_fx_by_currency(rows),
                prebook_total=_sum_twd(rows),
                prebook_count=int(len(rows)),
                sheet_rows=_sheet_rows(rows),
            ))
    result.sort(key=lambda t: (t.start, t.end), reverse=True)
    return result


def active_trip(trips: Iterable[Trip], today: date) -> Optional[Trip]:
    """
    The trip currently under way: a real trip (not the 行前 pseudo-entry) with
    start <= today and end >= today - TRIP_ACTIVE_GRACE_DAYS. Ties: latest end,
    then latest start. None when nothing qualifies.
    """
    today = _as_date(today)
    if today is None:
        return None
    floor = today - timedelta(days=TRIP_ACTIVE_GRACE_DAYS)
    candidates = [t for t in trips if not t.is_pending and t.start <= today and t.end >= floor]
    if not candidates:
        return None
    return max(candidates, key=lambda t: (t.end, t.start))


def trip_label(trip: Trip) -> str:
    """'🇸🇬 新加坡 09/05–09/07' (single-day trips: '🇲🇾 馬來西亞 09/08'; pending: '🧳 行前 · 尚未出發 …')."""
    flag = PREBOOK_PENDING_FLAG if trip.is_pending else COUNTRY_FLAG.get(trip.country, "")
    if trip.start == trip.end:
        span = trip.start.strftime("%m/%d")
    else:
        span = f"{trip.start.strftime('%m/%d')}–{trip.end.strftime('%m/%d')}"
    return " ".join(part for part in (flag, trip.country, span) if part)
