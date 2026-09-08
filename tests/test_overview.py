"""
Plan §5 steps 6-8 — ``overview.py`` pure logic.

Period resolution / comparison windows, filters, period_summary, the daily /
cumulative / monthly series and trip detection. Exact-date cases use hand-built
frames (``mk``); the conftest ``df`` (snapshot shifted so newest row == today)
covers realistic shapes. No Streamlit, no network, no sheet.
"""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

import overview as ov
from helpers import to_twd

TRAVEL, DAILY = ov.TRAVEL_TYPE, ov.DAILY_TYPE

_COLS = ["date", "type_1", "category_type", "amount", "account", "description", "country",
         "location", "notes", "currency", "orig_amount", "fx_rate", "sheet_row"]


def row(d, amount, *, type_1=DAILY, cat="🍽️ 飲食", account="菇菇", desc="x", country="台灣",
        location="臺南", notes="", currency="", orig=np.nan, rate=np.nan, sheet_row=None):
    return dict(date=d, type_1=type_1, category_type=cat, amount=amount, account=account,
                description=desc, country=country, location=location, notes=notes,
                currency=currency, orig_amount=orig, fx_rate=rate, sheet_row=sheet_row)


def mk(rows, legacy=False):
    """Frame shaped like SheetsAPI._process_data output (sheet_row auto = 2..N+1)."""
    frame = pd.DataFrame(rows, columns=_COLS)
    if len(frame):
        frame["sheet_row"] = [r if r is not None else i + 2 for i, r in enumerate(frame["sheet_row"])]
        frame["date"] = pd.to_datetime(frame["date"])
    else:
        frame["date"] = pd.Series(dtype="datetime64[ns]")
    frame["sheet_row"] = frame["sheet_row"].astype("int64")
    for c in ("amount", "orig_amount", "fx_rate"):
        frame[c] = pd.to_numeric(frame[c], errors="coerce").astype("float64")
    if legacy:
        frame = frame.drop(columns=["currency", "orig_amount", "fx_rate"])
    return frame


def foreign(d, amount, country, **kw):
    kw.setdefault("location", country)
    return row(d, amount, type_1=TRAVEL, country=country, **kw)


# ---------------------------------------------------------------------------
# resolve_period
# ---------------------------------------------------------------------------

class TestResolvePeriod:
    TUE = date(2026, 9, 8)          # a Tuesday

    def test_today(self):
        assert ov.resolve_period("今天", self.TUE) == (self.TUE, self.TUE)

    def test_week_monday_to_today_on_tuesday(self):
        assert ov.resolve_period("本週", self.TUE) == (date(2026, 9, 7), self.TUE)

    def test_week_on_monday_is_single_day(self):
        mon = date(2026, 9, 7)
        assert ov.resolve_period("本週", mon) == (mon, mon)

    def test_month_and_year(self):
        assert ov.resolve_period("本月", self.TUE) == (date(2026, 9, 1), self.TUE)
        assert ov.resolve_period("本年", self.TUE) == (date(2026, 1, 1), self.TUE)

    def test_last_month_full_across_year_boundary(self):
        assert ov.resolve_period("上月", date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
        assert ov.resolve_period("上月", date(2026, 3, 31)) == (date(2026, 2, 1), date(2026, 2, 28))

    def test_recent_windows_include_today(self):
        s, e = ov.resolve_period("最近7天", self.TUE)
        assert (e - s).days + 1 == 7 and e == self.TUE
        s, e = ov.resolve_period("最近30天", self.TUE)
        assert (e - s).days + 1 == 30 and e == self.TUE

    def test_all_uses_df_range_and_falls_back_to_today(self):
        frame = mk([row(date(2025, 3, 1), 1), row(date(2026, 8, 2), 1), row(pd.NaT, 1)])
        assert ov.resolve_period("全部", self.TUE, frame) == (date(2025, 3, 1), date(2026, 8, 2))
        assert ov.resolve_period("全部", self.TUE, None) == (self.TUE, self.TUE)
        assert ov.resolve_period("全部", self.TUE, mk([])) == (self.TUE, self.TUE)

    def test_custom_range_validation(self):
        assert ov.resolve_period("自訂範圍", self.TUE, custom=(date(2026, 9, 1), date(2026, 9, 3))) == \
            (date(2026, 9, 1), date(2026, 9, 3))
        assert ov.resolve_period("自訂範圍", self.TUE, custom=None) == (None, None)
        assert ov.resolve_period("自訂範圍", self.TUE, custom=(date(2026, 9, 3), date(2026, 9, 1))) == (None, None)
        assert ov.resolve_period("自訂範圍", self.TUE, custom=(self.TUE, self.TUE)) == (self.TUE, self.TUE)

    def test_unknown_label(self):
        assert ov.resolve_period("旅行", self.TUE) == (None, None)
        assert ov.resolve_period("", self.TUE) == (None, None)

    def test_accepts_timestamp_today(self):
        assert ov.resolve_period("今天", pd.Timestamp("2026-09-08 13:00")) == (self.TUE, self.TUE)


# ---------------------------------------------------------------------------
# comparison_window
# ---------------------------------------------------------------------------

class TestComparisonWindow:
    def test_today_vs_yesterday(self):
        d = date(2026, 9, 8)
        assert ov.comparison_window("今天", d, d) == (date(2026, 9, 7), date(2026, 9, 7), "昨天")

    def test_week_on_tuesday_is_last_week_mon_to_tue(self):
        s, e = ov.resolve_period("本週", date(2026, 9, 8))
        assert ov.comparison_window("本週", s, e) == (date(2026, 8, 31), date(2026, 9, 1), "上週同期")

    def test_month_on_the_31st_clamps(self):
        cs, ce, label = ov.comparison_window("本月", date(2026, 3, 1), date(2026, 3, 31))
        assert (cs, ce, label) == (date(2026, 2, 1), date(2026, 2, 28), "上月同期")
        cs, ce, _ = ov.comparison_window("本月", date(2026, 5, 1), date(2026, 5, 31))
        assert (cs, ce) == (date(2026, 4, 1), date(2026, 4, 30))

    def test_month_mid_month_same_day(self):
        assert ov.comparison_window("本月", date(2026, 9, 1), date(2026, 9, 8))[:2] == \
            (date(2026, 8, 1), date(2026, 8, 8))

    def test_month_january_goes_to_december(self):
        assert ov.comparison_window("本月", date(2026, 1, 1), date(2026, 1, 15))[:2] == \
            (date(2025, 12, 1), date(2025, 12, 15))

    def test_last_month_vs_the_month_before(self):
        s, e = ov.resolve_period("上月", date(2026, 3, 10))       # Feb 2026
        assert ov.comparison_window("上月", s, e) == (date(2026, 1, 1), date(2026, 1, 31), "前一個月")

    def test_year_same_md_and_feb29(self):
        assert ov.comparison_window("本年", date(2026, 1, 1), date(2026, 9, 8)) == \
            (date(2025, 1, 1), date(2025, 9, 8), "去年同期")
        assert ov.comparison_window("本年", date(2024, 1, 1), date(2024, 2, 29))[:2] == \
            (date(2023, 1, 1), date(2023, 2, 28))

    def test_recent_and_custom_precede_with_equal_length(self):
        s, e = ov.resolve_period("最近7天", date(2026, 9, 8))
        assert ov.comparison_window("最近7天", s, e) == (s - timedelta(days=7), s - timedelta(days=1), "前 7 天")
        s, e = ov.resolve_period("最近30天", date(2026, 9, 8))
        assert ov.comparison_window("最近30天", s, e)[:2] == (s - timedelta(days=30), s - timedelta(days=1))
        cs, ce, label = ov.comparison_window("自訂範圍", date(2026, 9, 1), date(2026, 9, 10))
        assert (cs, ce) == (date(2026, 8, 22), date(2026, 8, 31))
        assert (ce - cs).days == 9 and label == "前一段同長期間"

    def test_all_and_trip_have_no_comparison(self):
        assert ov.comparison_window("全部", date(2025, 1, 1), date(2026, 9, 8)) == (None, None, None)
        assert ov.comparison_window("旅行", date(2026, 9, 5), date(2026, 9, 7)) == (None, None, None)
        assert ov.comparison_window("本月", None, None) == (None, None, None)
        assert ov.comparison_window("nope", date(2026, 9, 1), date(2026, 9, 2)) == (None, None, None)


# ---------------------------------------------------------------------------
# canonical_category / apply_filters / slice_period
# ---------------------------------------------------------------------------

class TestFilters:
    def test_canonical_category_merges_alias_only(self):
        assert ov.canonical_category("📱通信") == "📱 通信"
        assert ov.canonical_category("📱 通信") == "📱 通信"
        assert ov.canonical_category(" 🍽️ 飲食 ") == "🍽️ 飲食"
        assert ov.canonical_category(None) == "" and ov.canonical_category(float("nan")) == ""

    def test_empty_lists_mean_no_filter(self):
        frame = mk([row(date(2026, 9, 1), 1), row(date(2026, 9, 2), 2, account="過兒")])
        out = ov.apply_filters(frame, {"accounts": [], "type_1": [], "categories": [], "countries": []})
        assert len(out) == 2
        assert len(ov.apply_filters(frame, {})) == 2 and len(ov.apply_filters(frame, None)) == 2

    def test_each_dimension(self):
        frame = mk([
            row(date(2026, 9, 1), 1, account="菇菇", cat="🍽️ 飲食"),
            row(date(2026, 9, 1), 2, account="過兒", cat="📱通信", type_1=TRAVEL, country="日本"),
            row(date(2026, 9, 1), 3, account="過兒", cat="📱 通信"),
        ])
        assert ov.apply_filters(frame, {"accounts": ["過兒"]})["amount"].tolist() == [2.0, 3.0]
        assert ov.apply_filters(frame, {"type_1": [TRAVEL]})["amount"].tolist() == [2.0]
        assert ov.apply_filters(frame, {"countries": ["台灣"]})["amount"].tolist() == [1.0, 3.0]
        assert ov.apply_filters(frame, {"accounts": ["過兒"], "countries": ["台灣"]})["amount"].tolist() == [3.0]

    def test_categories_compare_canonically_but_raw_column_untouched(self):
        frame = mk([row(date(2026, 9, 1), 2, cat="📱通信"), row(date(2026, 9, 1), 3, cat="📱 通信"),
                    row(date(2026, 9, 1), 4, cat="🍽️ 飲食")])
        out = ov.apply_filters(frame, {"categories": ["📱 通信"]})
        assert out["amount"].tolist() == [2.0, 3.0]
        assert out["category_type"].tolist() == ["📱通信", "📱 通信"]        # raw values survive
        assert ov.apply_filters(frame, {"categories": ["📱通信"]})["amount"].tolist() == [2.0, 3.0]
        assert frame["category_type"].tolist() == ["📱通信", "📱 通信", "🍽️ 飲食"]

    def test_underscore_keys_ignored_and_legacy_frame(self):
        frame = mk([row(date(2026, 9, 1), 1)], legacy=True)
        out = ov.apply_filters(frame, {"_label": "本月", "_today": date(2026, 9, 8)})
        assert len(out) == 1 and out["currency"].tolist() == [""]

    def test_slice_period_inclusive_and_drops_nat(self):
        frame = mk([row(date(2026, 8, 31), 1), row(date(2026, 9, 1), 2), row(date(2026, 9, 3), 3),
                    row(date(2026, 9, 4), 4), row(pd.NaT, 5)])
        out = ov.slice_period(frame, date(2026, 9, 1), date(2026, 9, 3))
        assert out["amount"].tolist() == [2.0, 3.0]
        assert len(ov.slice_period(frame, None, None)) == 0
        assert len(ov.slice_period(frame, date(2026, 9, 3), date(2026, 9, 1))) == 0
        assert len(ov.slice_period(mk([]), date(2026, 9, 1), date(2026, 9, 3))) == 0


# ---------------------------------------------------------------------------
# period_summary
# ---------------------------------------------------------------------------

@pytest.fixture
def fx_frame():
    """8 rows, 09/01-09/08 2026; 3 converted (SGD/JPY/MYR), the MYR one inconsistent."""
    sgd, jpy, myr = 25.2816, 0.205065, 7.75
    return mk([
        row(date(2026, 9, 1), 1000, cat="🍽️ 飲食", account="菇菇", desc="早餐"),
        row(date(2026, 9, 2), 18900, cat="🚗 交通", account="過兒", desc="機票", type_1=TRAVEL),
        row(date(2026, 9, 3), 2000, cat="📱通信", account="菇菇", desc="SIM"),
        row(date(2026, 9, 3), 500, cat="📱 通信", account="菇菇", desc="eSIM"),
        row(date(2026, 9, 4), np.nan, cat="🧴 日用", account="過兒", desc="壞掉"),
        row(date(2026, 9, 5), 0, cat="🧴 日用", account="過兒", desc="零元"),
        foreign(date(2026, 9, 6), to_twd(12.5, sgd, 2), "新加坡", desc="咖啡", currency="SGD", orig=12.5, rate=sgd),
        foreign(date(2026, 9, 7), to_twd(200000, jpy, 0), "日本", desc="住宿", currency="JPY", orig=200000, rate=jpy,
                cat="🏨 住宿"),
        foreign(date(2026, 9, 8), to_twd(210, myr, 2) + 50, "馬來西亞", desc="晚餐", currency="MYR", orig=210, rate=myr),
        foreign(date(2026, 9, 8), 300, "馬來西亞", desc="未標幣別"),
        foreign(date(2026, 9, 8), 100, "新加坡", desc="另一杯", currency="SGD", orig=4.0, rate=25.0),
        row(date(2026, 8, 31), 99999, desc="上月"),
    ])


class TestPeriodSummary:
    def test_totals_days_and_projection(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8), {"_label": "本月", "_today": date(2026, 9, 8)})
        expected = 1000 + 18900 + 2000 + 500 + 0 + to_twd(12.5, 25.2816, 2) + to_twd(200000, 0.205065, 0) \
            + to_twd(210, 7.75, 2) + 50 + 300 + 100
        assert s["total"] == expected
        assert s["count"] == 11                       # NaN-amount row still counts as a record
        assert s["days"] == 8
        assert s["daily_avg"] == pytest.approx(expected / 8)
        assert s["projected_month_end"] == round(expected / 8 * 30)
        assert s["start"] == date(2026, 9, 1) and s["end"] == date(2026, 9, 8) and s["label"] == "本月"

    def test_projection_only_for_month_label(self, fx_frame):
        assert ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8), {"_label": "本週"})["projected_month_end"] is None
        assert ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8))["projected_month_end"] is None

    def test_today_tile_follows_today_not_period(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 5), {"_today": date(2026, 9, 8)})
        assert s["today_count"] == 3 and s["today_total"] == to_twd(210, 7.75, 2) + 50 + 300 + 100
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 5), {"_today": date(2026, 9, 3)})
        assert (s["today_total"], s["today_count"]) == (2500, 2)

    def test_by_account_and_by_type1(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 5))
        assert s["by_account"] == {"過兒": 18900, "菇菇": 3500}
        assert list(s["by_account"]) == ["過兒", "菇菇"]           # desc by total
        assert s["by_type1"] == {DAILY: 3500, TRAVEL: 18900}
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 1))
        assert s["by_type1"] == {DAILY: 1000, TRAVEL: 0}          # both keys always present

    def test_top_categories_merge_alias_and_shares(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 5))
        cats = s["top_categories"]
        assert [c[0] for c in cats] == ["🚗 交通", "📱 通信", "🍽️ 飲食", "🧴 日用"]
        assert cats[1][1] == 2500 and cats[1][2] == pytest.approx(2500 / 22400)
        assert sum(c[2] for c in cats) == pytest.approx(1.0)
        assert s["other_categories_count"] == 1 and s["other_categories_total"] == 0

    def test_largest_and_fx_by_currency(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8))
        assert s["largest"]["description"] == "住宿"
        assert s["largest"]["amount"] == to_twd(200000, 0.205065, 0)
        assert s["largest"]["date"] == date(2026, 9, 7) and s["largest"]["sheet_row"] == 9
        assert s["fx_by_currency"] == {"JPY": Decimal("200000"), "MYR": Decimal("210.00"), "SGD": Decimal("16.50")}
        assert all(isinstance(v, Decimal) for v in s["fx_by_currency"].values())

    def test_data_check_counts_and_rows(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8))
        assert s["unparseable_count"] == 1 and s["unparseable_rows"][0]["description"] == "壞掉"
        assert s["unparseable_rows"][0]["amount"] is None
        assert s["zero_count"] == 1 and s["zero_rows"][0]["description"] == "零元"
        assert s["converted_count"] == 4
        assert s["inconsistent_count"] == 1 and s["inconsistent_rows"][0]["description"] == "晚餐"
        assert s["unlabeled_currency_count"] == 1 and s["unlabeled_currency_rows"][0]["description"] == "未標幣別"

    def test_inconsistent_when_rate_missing(self):
        frame = mk([foreign(date(2026, 9, 1), 300, "新加坡", currency="SGD", orig=12.0)])
        s = ov.period_summary(frame, date(2026, 9, 1), date(2026, 9, 1))
        assert s["converted_count"] == 1 and s["inconsistent_count"] == 1

    def test_filters_apply_before_summary(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8), {"accounts": ["菇菇"], "type_1": [DAILY]})
        assert s["total"] == 3500 and s["count"] == 3
        s = ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8), {"categories": ["📱 通信"]})
        assert s["total"] == 2500 and s["top_categories"] == [("📱 通信", 2500, 1.0)]

    def test_empty_period_and_empty_frame(self, fx_frame):
        s = ov.period_summary(fx_frame, date(2027, 1, 1), date(2027, 1, 31), {"_label": "本月"})
        assert s["total"] == 0 and s["count"] == 0 and s["days"] == 31
        assert s["largest"] is None and s["top_categories"] == [] and s["projected_month_end"] == 0
        assert s["by_type1"] == {DAILY: 0, TRAVEL: 0}
        s = ov.period_summary(pd.DataFrame(), date(2026, 9, 1), date(2026, 9, 8))
        assert s["total"] == 0 and s["count"] == 0 and s["fx_by_currency"] == {}
        s = ov.period_summary(fx_frame, None, None)
        assert s["total"] == 0 and s["days"] == 0 and s["daily_avg"] == 0.0

    def test_legacy_frame_without_fx_columns(self, fx_frame):
        legacy = fx_frame.drop(columns=["currency", "orig_amount", "fx_rate"])
        s = ov.period_summary(legacy, date(2026, 9, 1), date(2026, 9, 8))
        assert s["converted_count"] == 0 and s["inconsistent_count"] == 0 and s["fx_by_currency"] == {}
        assert s["unlabeled_currency_count"] == 5      # every foreign row lacks a currency
        assert s["total"] == ov.period_summary(fx_frame, date(2026, 9, 1), date(2026, 9, 8))["total"]

    def test_amount_strings_are_coerced_not_zeroed(self):
        frame = mk([row(date(2026, 9, 1), 10), row(date(2026, 9, 1), 5)])
        frame["amount"] = pd.Series(["10", "abc"], dtype="object")
        s = ov.period_summary(frame, date(2026, 9, 1), date(2026, 9, 1))
        assert s["total"] == 10 and s["unparseable_count"] == 1 and s["count"] == 2

    def test_snapshot_month_matches_pandas(self, df, today):
        start, end = ov.resolve_period("本月", today)
        s = ov.period_summary(df, start, end, {"_label": "本月", "_today": today})
        sliced = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
        assert s["total"] == round(sliced["amount"].dropna().sum())
        assert s["count"] == len(sliced)
        assert s["days"] == today.day
        assert s["today_count"] == int((df["date"] == pd.Timestamp(today)).sum())
        assert s["unparseable_count"] == int(sliced["amount"].isna().sum())

    def test_snapshot_all_time_alias_merge(self, df, today):
        start, end = ov.resolve_period("全部", today, df)
        s = ov.period_summary(df, start, end)
        names = [c[0] for c in s["top_categories"]]
        assert "📱通信" not in names and "📱 通信" in names
        assert s["count"] == int(df["date"].notna().sum())
        assert s["unparseable_count"] == int(df["amount"].isna().sum())

    def test_snapshot_with_injected_converted_rows(self, df, today):
        sgd, myr = 25.2816, 7.75
        extra = mk([
            foreign(today, to_twd(12.5, sgd, 2), "新加坡", currency="SGD", orig=12.5, rate=sgd, sheet_row=90001),
            foreign(today, to_twd(210, myr, 2) + 50, "馬來西亞", currency="MYR", orig=210, rate=myr, sheet_row=90002),
        ])
        both = pd.concat([df, extra], ignore_index=True)
        start, end = ov.resolve_period("本月", today)
        s = ov.period_summary(both, start, end)
        base = ov.period_summary(df, start, end)
        assert s["converted_count"] == 2 and s["inconsistent_count"] == 1
        assert s["inconsistent_rows"][0]["sheet_row"] == 90002
        assert s["fx_by_currency"] == {"MYR": Decimal("210.00"), "SGD": Decimal("12.50")}
        assert s["total"] == base["total"] + to_twd(12.5, sgd, 2) + to_twd(210, myr, 2) + 50


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------

class TestSeries:
    def test_daily_series_covers_every_calendar_day(self, fx_frame):
        out = ov.daily_series(fx_frame, date(2026, 8, 25), date(2026, 9, 8))
        assert len(out) == 15 and list(out.columns) == ["date", "total"]
        assert out["date"].iloc[0] == pd.Timestamp("2026-08-25") and out["date"].iloc[-1] == pd.Timestamp("2026-09-08")
        by_day = dict(zip(out["date"].dt.date, out["total"]))
        assert by_day[date(2026, 8, 25)] == 0 and by_day[date(2026, 8, 31)] == 99999
        assert by_day[date(2026, 9, 3)] == 2500 and by_day[date(2026, 9, 4)] == 0
        assert out["total"].dtype == "int64"

    def test_daily_series_single_day_and_invalid(self, fx_frame):
        out = ov.daily_series(fx_frame, date(2026, 9, 2), date(2026, 9, 2))
        assert len(out) == 1 and out["total"].iloc[0] == 18900
        assert len(ov.daily_series(fx_frame, None, None)) == 0
        assert len(ov.daily_series(mk([]), date(2026, 9, 1), date(2026, 9, 3))) == 3

    def test_cumulative_series(self, fx_frame):
        out = ov.cumulative_series(fx_frame, date(2026, 9, 1), date(2026, 9, 5))
        assert out["day_index"].tolist() == [1, 2, 3, 4, 5]
        assert out["total"].tolist() == [1000, 18900, 2500, 0, 0]
        assert out["cumulative"].tolist() == [1000, 19900, 22400, 22400, 22400]

    def test_snapshot_daily_series_length_equals_period_days(self, df, today):
        start, end = ov.resolve_period("最近30天", today)
        assert len(ov.daily_series(df, start, end)) == 30
        cum = ov.cumulative_series(df, start, end)
        assert len(cum) == 30 and cum["cumulative"].iloc[-1] == ov.period_summary(df, start, end)["total"]

    def test_monthly_series_fills_gaps(self):
        frame = mk([row(date(2026, 1, 5), 100), row(date(2026, 1, 6), np.nan),
                    row(date(2026, 4, 1), 50), row(pd.NaT, 999)])
        out = ov.monthly_series(frame)
        assert out["month"].tolist() == ["2026-01", "2026-02", "2026-03", "2026-04"]
        assert out["total"].tolist() == [100, 0, 0, 50]
        assert out["count"].tolist() == [2, 0, 0, 1]          # NaN-amount row is still a row

    def test_monthly_series_empty_and_snapshot(self, df):
        assert list(ov.monthly_series(pd.DataFrame()).columns) == ["month", "total", "count"]
        assert len(ov.monthly_series(mk([]))) == 0
        out = ov.monthly_series(df)
        first, last = df["date"].min().to_period("M"), df["date"].max().to_period("M")
        assert len(out) == (last - first).n + 1
        assert out["total"].sum() == round(df["amount"].dropna().sum())


# ---------------------------------------------------------------------------
# trips
# ---------------------------------------------------------------------------

def _trip(trips, country):
    found = [t for t in trips if t.country == country]
    assert len(found) == 1, [ov.trip_label(t) for t in trips]
    return found[0]


class TestTrips:
    def test_golden_snapshot_shape(self):
        """new_to_fill.csv geometry (real dates): 澳洲 01/14-01/30 + 12/06 prebook + 台灣 airport rows,
        日本 06/13-06/20 + 06/05 insurance, 加拿大 upcoming, 台灣 domestic runs -> 行前/pending."""
        frame = mk([
            foreign(date(2026, 6, 17), 26495, "加拿大", desc="加拿大機票", cat="🚗 交通"),
            foreign(date(2026, 6, 17), 47654, "加拿大", desc="加拿大機票", cat="🚗 交通"),
            row(date(2026, 3, 22), 460, type_1=TRAVEL, desc="安平蝦捲"),                 # 旅行+台灣
            row(date(2026, 1, 31), 400, type_1=TRAVEL, desc="Godiva", location="桃園"),  # return-day airport
            *[foreign(date(2026, 1, d), 1000, "澳洲") for d in range(14, 31)],
            row(date(2026, 1, 14), 110, type_1=TRAVEL, desc="紅豆餅", location="桃園"),   # departure-day airport
            foreign(date(2025, 12, 26), 1519, "加拿大", desc="加拿大機票", cat="🚗 交通"),
            row(date(2025, 12, 14), 7068, type_1=TRAVEL, desc="泰國住宿", cat="🏨 住宿"),
            foreign(date(2025, 12, 6), 3034, "澳洲", desc="Puffing Billy", cat="🎮 娛樂"),  # prebook, 澳洲-filed
            *[foreign(date(2025, 6, d), 500, "日本") for d in range(13, 21)],
            foreign(date(2025, 6, 5), 5493, "日本", desc="旅平險", cat="🛡️ 保險"),
            row(date(2025, 4, 19), 640, type_1=TRAVEL, desc="飛牛牧場", location="苗栗"),
            row(date(2024, 9, 6), 4285, type_1=TRAVEL, desc="墾丁民宿", cat="🏨 住宿"),   # > 180 d before 日本
            row(date(2024, 9, 7), 832, type_1=TRAVEL, desc="海生館"),
            row(date(2025, 1, 24), 40, desc="日常台北捷運", cat="🚗 交通"),               # 日常: ignored
        ])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert [t.country for t in trips] == ["加拿大", "澳洲", "日本", ov.PREBOOK_PENDING]
        assert "台灣" not in {t.country for t in trips}

        au = _trip(trips, "澳洲")
        assert (au.start, au.end) == (date(2026, 1, 14), date(2026, 1, 30))
        assert au.in_trip_count == 17 and au.in_trip_total == 17000
        # 行前: Puffing Billy (澳洲-filed, 39 d before), 泰國住宿 (next trip within 180 d),
        # 紅豆餅 (departure day), Godiva (end + 1 day)
        assert au.prebook_count == 4 and au.prebook_total == 3034 + 7068 + 110 + 400
        assert au.count == 21 and au.total == 17000 + au.prebook_total
        assert au.days == 17 and ov.trip_label(au) == "🇦🇺 澳洲 01/14–01/30"

        jp = _trip(trips, "日本")
        assert (jp.start, jp.end) == (date(2025, 6, 13), date(2025, 6, 20))
        assert jp.in_trip_count == 8 and jp.prebook_count == 2      # 旅平險 + 飛牛牧場 (55 d before)
        assert jp.prebook_total == 5493 + 640

        ca = _trip(trips, "加拿大")
        assert (ca.start, ca.end) == (date(2026, 6, 17), date(2026, 6, 17))
        assert ca.in_trip_count == 2 and ca.in_trip_total == 26495 + 47654
        assert ca.prebook_count == 2 and ca.prebook_total == 1519 + 460   # 12/26 flight (173 d) + 安平蝦捲
        assert ov.trip_label(ca) == "🇨🇦 加拿大 06/17"

        pending = _trip(trips, ov.PREBOOK_PENDING)
        assert (pending.start, pending.end) == (date(2024, 9, 6), date(2024, 9, 7))
        assert pending.total == pending.prebook_total == 4285 + 832 and pending.is_pending
        assert pending.count == pending.prebook_count == 2
        assert ov.trip_label(pending).startswith("🧳 行前 · 尚未出發 09/06–09/07")

        all_rows = sorted(r for t in trips for r in t.sheet_rows)
        expected = sorted(int(v) for v in frame.loc[frame["type_1"] == TRAVEL, "sheet_row"])
        assert all_rows == expected                                   # every 旅行 row lands exactly once

    def test_consecutive_countries_are_two_trips(self):
        frame = mk([
            foreign(date(2026, 9, 5), 100, "新加坡", currency="SGD", orig=4.0, rate=25.0),
            foreign(date(2026, 9, 6), 200, "新加坡", currency="SGD", orig=8.0, rate=25.0),
            foreign(date(2026, 9, 7), 300, "新加坡"),
            foreign(date(2026, 9, 8), 400, "馬來西亞", currency="MYR", orig=51.5, rate=7.77),
        ])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert [ov.trip_label(t) for t in trips] == ["🇲🇾 馬來西亞 09/08", "🇸🇬 新加坡 09/05–09/07"]
        sg, my = trips[1], trips[0]
        assert sg.total == 600 and sg.count == 3 and sg.fx_by_currency == {"SGD": Decimal("12.00")}
        assert my.total == 400 and my.fx_by_currency == {"MYR": Decimal("51.50")}
        assert sg.sheet_rows == [2, 3, 4] and my.sheet_rows == [5]

    def test_gap_three_days_keeps_gap_four_splits(self):
        base = date(2026, 9, 1)

        def run(days_a, gap, days_b):
            rows = [foreign(base + timedelta(days=d), 1, "日本") for d in range(days_a)]
            second = base + timedelta(days=days_a - 1 + gap)
            rows += [foreign(second + timedelta(days=d), 2, "日本") for d in range(days_b)]
            return ov.detect_trips(mk(rows), date(2026, 12, 31)), second

        trips, _ = run(5, 3, 5)                       # 09/01-09/05, next row 09/08 (gap 3) -> one trip
        assert len(trips) == 1 and (trips[0].start, trips[0].end) == (base, date(2026, 9, 12))
        trips, second = run(5, 4, 5)                  # gap 4 -> split
        assert len(trips) == 2 and trips[0].start == second and trips[1].end == date(2026, 9, 5)
        assert all(t.prebook_count == 0 for t in trips)
        # a 1-day cluster 4 days ahead of a trip splits too, but is then attached as 行前 (short cluster)
        trips, second = run(1, 4, 5)
        assert len(trips) == 1 and trips[0].start == second and trips[0].prebook_count == 1

    def test_long_earlier_trip_is_not_merged_as_prebook(self):
        frame = mk([*[foreign(date(2026, 3, d), 1, "日本") for d in range(1, 6)],
                    *[foreign(date(2026, 5, d), 1, "日本") for d in range(1, 4)]])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert [(t.start, t.end) for t in trips] == [(date(2026, 5, 1), date(2026, 5, 3)), (date(2026, 3, 1), date(2026, 3, 5))]
        assert all(t.prebook_count == 0 for t in trips)

    def test_short_cluster_outside_window_stays_a_trip(self):
        frame = mk([foreign(date(2025, 1, 10), 1, "日本"), foreign(date(2026, 1, 10), 1, "日本")])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert len(trips) == 2 and all(t.prebook_count == 0 for t in trips)

    def test_taiwan_travel_rows_never_form_a_taiwan_trip(self):
        frame = mk([row(date(2026, 9, 1), 100, type_1=TRAVEL, desc="墾丁"),
                    row(date(2026, 9, 2), 200, type_1=TRAVEL, desc="墾丁"),
                    row(date(2026, 9, 3), 50, type_1=TRAVEL, country="", desc="無國家")])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert len(trips) == 1 and trips[0].country == ov.PREBOOK_PENDING
        assert trips[0].total == 350 and trips[0].count == 3
        assert ov.active_trip(trips, date(2026, 9, 4)) is None

    def test_taiwan_rows_split_into_pending_runs_and_attach_within_window(self):
        frame = mk([row(date(2026, 1, 1), 1, type_1=TRAVEL), row(date(2026, 1, 10), 2, type_1=TRAVEL),
                    row(date(2026, 6, 1), 3, type_1=TRAVEL, desc="機票"),
                    foreign(date(2026, 9, 1), 100, "韓國"), foreign(date(2026, 9, 2), 100, "韓國")])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        kr = _trip(trips, "韓國")
        assert kr.prebook_count == 1 and kr.prebook_total == 3 and kr.total == 203
        pending = [t for t in trips if t.is_pending]
        assert [(t.start, t.total) for t in pending] == [(date(2026, 1, 10), 2), (date(2026, 1, 1), 1)]

    def test_trailing_taiwan_row_beyond_gap_goes_to_next_trip(self):
        frame = mk([foreign(date(2026, 3, 1), 1, "日本"), row(date(2026, 3, 5), 5, type_1=TRAVEL),
                    foreign(date(2026, 4, 1), 1, "韓國")])
        trips = ov.detect_trips(frame, date(2026, 9, 8))
        assert _trip(trips, "韓國").prebook_total == 5 and _trip(trips, "日本").prebook_total == 0

    def test_nan_amount_rows_are_counted_not_zeroed(self):
        frame = mk([foreign(date(2026, 9, 1), np.nan, "日本"), foreign(date(2026, 9, 1), 100, "日本")])
        t = ov.detect_trips(frame, date(2026, 9, 8))[0]
        assert t.total == 100 and t.count == 2

    def test_empty_legacy_and_no_travel_frames(self):
        assert ov.detect_trips(pd.DataFrame(), date(2026, 9, 8)) == []
        assert ov.detect_trips(mk([]), date(2026, 9, 8)) == []
        assert ov.detect_trips(mk([row(date(2026, 9, 1), 1)]), date(2026, 9, 8)) == []
        legacy = mk([foreign(date(2026, 9, 1), 1, "日本")], legacy=True)
        trips = ov.detect_trips(legacy, date(2026, 9, 8))
        assert len(trips) == 1 and trips[0].fx_by_currency == {}

    def test_sorted_by_start_desc(self):
        frame = mk([foreign(date(2026, 1, 1), 1, "日本"), foreign(date(2026, 5, 1), 1, "韓國"),
                    foreign(date(2026, 3, 1), 1, "澳洲")])
        assert [t.country for t in ov.detect_trips(frame, date(2026, 9, 8))] == ["韓國", "澳洲", "日本"]

    def test_active_trip_grace_and_tiebreak(self):
        a = ov.Trip("新加坡", date(2026, 9, 1), date(2026, 9, 5), 1, 1)
        b = ov.Trip("馬來西亞", date(2026, 9, 3), date(2026, 9, 5), 1, 1)      # same end, later start
        c = ov.Trip("日本", date(2026, 9, 2), date(2026, 9, 6), 1, 1)         # latest end
        pend = ov.Trip(ov.PREBOOK_PENDING, date(2026, 9, 7), date(2026, 9, 8), 1, 1)
        assert ov.active_trip([a, b], date(2026, 9, 8)) is b
        assert ov.active_trip([a, b, c], date(2026, 9, 8)) is c
        assert ov.active_trip([a, b, c], date(2026, 9, 9)) is c               # end + 3 == today
        assert ov.active_trip([a, b, c], date(2026, 9, 10)) is None
        assert ov.active_trip([pend], date(2026, 9, 8)) is None
        assert ov.active_trip([], date(2026, 9, 8)) is None

    def test_active_trip_ignores_future_trips(self):
        future = ov.Trip("加拿大", date(2026, 10, 1), date(2026, 10, 5), 1, 1)
        assert ov.active_trip([future], date(2026, 9, 8)) is None
        assert ov.active_trip([future], date(2026, 10, 1)) is future

    def test_snapshot_trips(self, df, today):
        """Shifted snapshot: newest rows (加拿大 flights) land on today -> active trip."""
        trips = ov.detect_trips(df, today)
        countries = [t.country for t in trips]
        assert countries[0] == "加拿大" and trips[0].start == today
        assert "台灣" not in countries and "澳洲" in countries and countries.count("日本") == 2
        au = _trip(trips, "澳洲")
        assert au.days == 17 and au.in_trip_count == 103 - 1 and au.prebook_count >= 1
        assert ov.active_trip(trips, today) is trips[0]
        travel_rows = set(int(v) for v in df.loc[df["type_1"] == TRAVEL, "sheet_row"])
        assert set(r for t in trips for r in t.sheet_rows) == travel_rows
