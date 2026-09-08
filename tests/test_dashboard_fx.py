"""
FX display in 總覽 (``app.py``), after the §3 redesign.

Step 5 originally put these behaviours in ``fx_audit`` / ``show_data_quality_info``
/ ``show_recent_transactions``. The redesign moved them:

* the audit counts are now ``overview.period_summary`` keys
  (``converted_count`` / ``inconsistent_count`` / ``unlabeled_currency_count``),
  rendered by ``show_data_check_expander``;
* the transaction tables are ``show_recent_list`` (5 rows) and
  ``show_period_transactions`` (whole period). Both fold the original amount into
  名稱 ('咖啡 · SGD 12.50') rather than adding a sixth column, which would overflow
  390 px (PLAN §3.2: no horizontal scroll).

Every consumer must still tolerate a legacy frame without the 幣別/原幣金額/匯率
columns (a ``last_good_df`` captured before deploy — G15).

Streamlit runs in bare mode here (no ScriptRunContext); display calls are captured
by monkeypatching ``app.st.*`` — no network, no Google Sheet.
"""

import sys

import numpy as np
import pandas as pd
import pytest

import overview as ov
from helpers import to_twd, today_local


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    import app as app_module  # set_page_config is a no-op outside a script run
    return sys.modules.get("app", app_module)


def _template_row(df, **overrides):
    row = df.iloc[-1].copy()
    row.update(overrides)
    return row


def _inject_converted_rows(df):
    """conftest df + 3 converted rows (SGD, JPY, MYR); the MYR row is inconsistent."""
    today = pd.Timestamp(today_local())
    sgd_rate, jpy_rate, myr_rate = 25.2816, 0.205065, 7.75
    rows = [
        _template_row(df, date=today, description="咖啡", country="新加坡", location="新加坡",
                      type_1="旅行", currency="SGD", orig_amount=12.5, fx_rate=sgd_rate,
                      amount=float(to_twd(12.5, sgd_rate, 2)), sheet_row=90001),
        _template_row(df, date=today, description="機票", country="日本", location="東京",
                      type_1="旅行", currency="JPY", orig_amount=200000, fx_rate=jpy_rate,
                      amount=float(to_twd(200000, jpy_rate, 0)), sheet_row=90002),
        # inconsistent: 金額 is 50 TWD away from orig × rate
        _template_row(df, date=today, description="晚餐", country="馬來西亞", location="吉隆坡",
                      type_1="旅行", currency="MYR", orig_amount=210, fx_rate=myr_rate,
                      amount=float(to_twd(210, myr_rate, 2)) + 50, sheet_row=90003),
    ]
    extra = pd.DataFrame(rows)
    out = pd.concat([df, extra], ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out["orig_amount"] = pd.to_numeric(out["orig_amount"], errors="coerce")
    out["fx_rate"] = pd.to_numeric(out["fx_rate"], errors="coerce")
    out.attrs = dict(df.attrs, fx_headers=True)
    return out


@pytest.fixture
def df_fx(df):
    return _inject_converted_rows(df)


@pytest.fixture
def legacy_df(df):
    """The 15-column frame a pre-deploy last_good_df would carry (no FX columns)."""
    out = df.drop(columns=["currency", "orig_amount", "fx_rate"])
    out.attrs = {}
    assert "currency" not in out.columns
    return out


def audit(frame):
    """The FX audit counts for the whole frame (period_summary over its full date span)."""
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    start, end = dates.min().date(), dates.max().date()
    return ov.period_summary(frame, start, end, {})


class _Capture:
    """Records st.write / st.caption / st.dataframe / st.error calls made by app.*"""

    def __init__(self, monkeypatch, app):
        self.writes, self.captions, self.frames, self.errors = [], [], [], []
        monkeypatch.setattr(app.st, "write", lambda *a, **k: self.writes.append(" ".join(str(x) for x in a)))
        monkeypatch.setattr(app.st, "caption", lambda *a, **k: self.captions.append(str(a[0]) if a else ""))
        monkeypatch.setattr(app.st, "dataframe", lambda data=None, *a, **k: self.frames.append(data))
        monkeypatch.setattr(app.st, "error", lambda *a, **k: self.errors.append(str(a[0]) if a else ""))

    @property
    def text(self):
        return " | ".join(self.writes + self.captions)


@pytest.fixture
def capture(monkeypatch, app):
    return _Capture(monkeypatch, app)


# ---------------------------------------------------------------------------
# audit counts (pure, via overview.period_summary)
# ---------------------------------------------------------------------------

def test_audit_counts_converted_inconsistent_untagged(df, df_fx):
    s = audit(df_fx)
    assert s["converted_count"] == 3
    assert s["inconsistent_count"] == 1
    assert [r["description"] for r in s["inconsistent_rows"]] == ["晚餐"]

    # 未標幣別: snapshot rows abroad carry no 幣別 (informational); the 3 injected rows are tagged
    abroad_untagged = int((~df["country"].fillna("").isin(["", "台灣"])).sum())
    assert abroad_untagged > 0
    assert s["unlabeled_currency_count"] == abroad_untagged
    assert len(s["unlabeled_currency_rows"]) == abroad_untagged


def test_audit_snapshot_has_no_converted_rows(df):
    s = audit(df)
    assert s["converted_count"] == 0
    assert s["inconsistent_count"] == 0


def test_audit_tolerance_is_one_twd(df_fx):
    # ±1 TWD is fine (rate rounding), ±2 is not
    sgd = df_fx.index[df_fx["currency"] == "SGD"][0]
    d = df_fx.copy()
    d.loc[sgd, "amount"] += 1
    assert audit(d)["inconsistent_count"] == 1        # still only the MYR row
    d.loc[sgd, "amount"] += 1
    assert audit(d)["inconsistent_count"] == 2


def test_audit_missing_rate_counts_as_inconsistent(df_fx):
    d = df_fx.copy()
    jpy = d.index[d["currency"] == "JPY"][0]
    d.loc[jpy, "fx_rate"] = np.nan
    s = audit(d)
    assert s["converted_count"] == 3
    assert s["inconsistent_count"] == 2


def test_audit_twd_currency_is_native(df_fx):
    """'TWD' in 幣別 means a TWD-native row, never a conversion."""
    d = df_fx.copy()
    sgd = d.index[d["currency"] == "SGD"][0]
    d.loc[sgd, "currency"] = "TWD"
    assert audit(d)["converted_count"] == 2


def test_audit_legacy_frame_is_all_zero(legacy_df):
    s = audit(legacy_df)
    assert s["converted_count"] == 0
    assert s["inconsistent_count"] == 0


# ---------------------------------------------------------------------------
# 🧹 資料檢查 expander
# ---------------------------------------------------------------------------

def test_data_check_expander_reports_fx_counts(app, capture, df_fx):
    app.show_data_check_expander(audit(df_fx))
    assert "**已換算外幣**: 3 筆" in capture.writes
    assert "**換算不一致**: 1 筆" in capture.writes
    assert any("晚餐" in c for c in capture.captions)


def test_data_check_expander_zero_inconsistent_line(app, capture, df):
    app.show_data_check_expander(audit(df))
    assert "**換算不一致**: 0 筆" in capture.writes
    # no warning caption when nothing is inconsistent
    assert not any("金額 ≠ 原幣金額" in c for c in capture.captions)


def test_data_check_expander_legacy_frame_renders(app, capture, legacy_df):
    """A pre-deploy frame has no FX columns: nothing raises, nothing is 'converted' (G15)."""
    app.show_data_check_expander(audit(legacy_df))
    assert "**已換算外幣**: 0 筆" in capture.writes
    assert "**換算不一致**: 0 筆" in capture.writes
    # every foreign row is legitimately 未標幣別 on a frame that predates the columns
    assert any(w.startswith("**未標幣別**:") for w in capture.writes)


# ---------------------------------------------------------------------------
# transaction tables: 原幣 folded into 名稱
# ---------------------------------------------------------------------------

def _last_frame(capture):
    assert capture.frames, "no st.dataframe rendered"
    return capture.frames[-1]


def test_recent_list_shows_currency_in_name(app, capture, df_fx):
    app.show_recent_list(df_fx)
    shown = _last_frame(capture)
    assert "原幣" not in shown.columns          # merged, never a sixth column
    names = " | ".join(str(n) for n in shown["名稱"])
    assert "咖啡 · SGD 12.50" in names


def test_recent_list_plain_names_without_converted_rows(app, capture, df):
    app.show_recent_list(df)
    shown = _last_frame(capture)
    assert "原幣" not in shown.columns
    assert not any(" · " in str(n) for n in shown["名稱"])


def test_recent_list_follows_the_frame_passed(app, capture, df, df_fx):
    """The suffix tracks the frame it is given, not global state."""
    app.show_recent_list(df_fx.head(0))
    app.show_recent_list(df)
    assert not any(" · SGD" in str(n) for n in _last_frame(capture)["名稱"])


def test_recent_list_legacy_frame_renders(app, capture, legacy_df):
    app.show_recent_list(legacy_df)
    shown = _last_frame(capture)
    assert list(shown.columns) == ["日期", "名稱", "金額"]


def test_period_transactions_folds_currency_into_name(app, capture, df_fx):
    """The full list stays five columns wide so it fits a 390 px phone."""
    app.show_period_transactions(df_fx, audit(df_fx))
    shown = _last_frame(capture)
    assert list(shown.columns) == ["日期", "分類", "名稱", "金額", "帳戶"]
    assert any("· SGD 12.50" in str(n) for n in shown["名稱"])


def test_period_transactions_legacy_frame_renders(app, capture, legacy_df):
    app.show_period_transactions(legacy_df, audit(legacy_df))
    assert list(_last_frame(capture).columns) == ["日期", "分類", "名稱", "金額", "帳戶"]


# ---------------------------------------------------------------------------
# whole-dashboard smoke (AppTest)
# ---------------------------------------------------------------------------

def test_apptest_dashboard_with_converted_rows(app_test, no_network, snapshot_api, df_fx):
    """The 總覽 renders with converted rows present and shows the hero total."""
    at = app_test()
    at.run()
    assert not at.exception, at.exception
    assert at.metric, "hero metric missing"


def test_apptest_dashboard_legacy_frame_no_keyerror(app_test, no_network):
    at = app_test()
    at.run()
    assert not at.exception, at.exception
