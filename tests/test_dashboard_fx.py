"""
Plan §5 step 5 — 總覽 minimal FX display (``app.py``).

* ``show_recent_transactions`` gains a 💱 原幣 column only when the frame holds a
  converted row.
* ``show_data_quality_info`` reports 已換算外幣 / 換算不一致 / 未標幣別.
* Every consumer tolerates a legacy frame without the 幣別/原幣金額/匯率 columns
  (a ``last_good_df`` captured before deploy — G15).

Streamlit runs in bare mode here (no ScriptRunContext); display calls are
captured by monkeypatching ``app.st.*`` — no network, no Google Sheet.
"""

import sys

import numpy as np
import pandas as pd
import pytest

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
# fx_audit (pure)
# ---------------------------------------------------------------------------

def test_fx_audit_counts_converted_inconsistent_untagged(app, df, df_fx):
    audit = app.fx_audit(df_fx)
    assert audit["converted"] == 3
    assert audit["inconsistent"] == 1
    assert audit["inconsistent_labels"] == [f"{today_local():%m/%d} 晚餐"]

    # 未標幣別: snapshot rows abroad carry no 幣別 (informational); the 3 injected rows are tagged
    abroad_untagged = int((~df["country"].fillna("").isin(["", "台灣"])).sum())
    assert abroad_untagged > 0
    assert audit["untagged"] == abroad_untagged
    assert len(audit["untagged_labels"]) == abroad_untagged


def test_fx_audit_snapshot_has_no_converted_rows(app, df):
    audit = app.fx_audit(df)
    assert audit["converted"] == 0
    assert audit["inconsistent"] == 0


def test_fx_audit_tolerance_is_one_twd(app, df_fx):
    # ±1 TWD is fine (rate rounding), ±2 is not
    sgd = df_fx.index[df_fx["currency"] == "SGD"][0]
    d = df_fx.copy()
    d.loc[sgd, "amount"] += 1
    assert app.fx_audit(d)["inconsistent"] == 1        # still only the MYR row
    d.loc[sgd, "amount"] += 1
    assert app.fx_audit(d)["inconsistent"] == 2


def test_fx_audit_missing_rate_counts_as_inconsistent(app, df_fx):
    d = df_fx.copy()
    jpy = d.index[d["currency"] == "JPY"][0]
    d.loc[jpy, "fx_rate"] = np.nan
    audit = app.fx_audit(d)
    assert audit["converted"] == 3
    assert audit["inconsistent"] == 2


def test_fx_audit_twd_currency_is_native(app, df_fx):
    d = df_fx.copy()
    d.loc[d["currency"] == "SGD", "currency"] = "twd"
    assert app.fx_audit(d)["converted"] == 2
    assert not app.converted_mask(d)[d["currency"] == "twd"].any()


def test_fx_audit_legacy_frame_is_all_zero(app, legacy_df):
    audit = app.fx_audit(legacy_df)
    assert audit == {"converted": 0, "inconsistent": 0, "untagged": 0,
                     "inconsistent_labels": [], "untagged_labels": []}
    assert not app.converted_mask(legacy_df).any()
    assert app.fx_audit(pd.DataFrame()) == audit
    assert app.fx_audit(None) == audit


# ---------------------------------------------------------------------------
# show_data_quality_info
# ---------------------------------------------------------------------------

def test_data_quality_info_reports_fx_counts(app, capture, df_fx):
    app.show_data_quality_info(df_fx)
    assert not capture.errors
    assert "**已換算外幣**: 3 筆" in capture.writes
    assert "**換算不一致**: 1 筆" in capture.writes
    assert any("晚餐" in c and "編輯" in c for c in capture.captions)
    untagged = [w for w in capture.writes if w.startswith("**未標幣別**")]
    assert untagged and untagged[0].endswith("筆")


def test_data_quality_info_zero_inconsistent_line(app, capture, df):
    app.show_data_quality_info(df)
    assert "**已換算外幣**: 0 筆" in capture.writes
    assert "**換算不一致**: 0 筆" in capture.writes
    assert not any("編輯" in c for c in capture.captions)


def test_data_quality_info_legacy_frame_renders_without_fx_lines(app, capture, legacy_df):
    app.show_data_quality_info(legacy_df)          # must not raise KeyError
    assert not capture.errors
    assert any(w.startswith("**有效記錄數量**") for w in capture.writes)
    assert not any("已換算外幣" in w or "換算不一致" in w or "未標幣別" in w for w in capture.writes)


# ---------------------------------------------------------------------------
# show_recent_transactions
# ---------------------------------------------------------------------------

def test_recent_transactions_shows_orig_column_when_converted(app, capture, df_fx):
    app.show_recent_transactions(df_fx)
    assert not capture.errors, capture.errors
    shown = capture.frames[0]
    assert "💱 原幣" in shown.columns
    cols = list(shown.columns)
    assert cols.index("💱 原幣") == cols.index("💰 金額") + 1
    labels = shown["💱 原幣"].tolist()
    assert "SGD 12.50" in labels
    assert "JPY 200,000" in labels
    assert "MYR 210.00" in labels
    # TWD-native rows show an empty cell, never 'nan'
    assert (shown["💱 原幣"] == "").sum() == len(shown) - 3
    assert not any("nan" in str(x).lower() for x in labels)
    # TWD figure still the converted amount
    assert f"NT${to_twd(12.5, 25.2816, 2):,}" in shown["💰 金額"].tolist()


def test_recent_transactions_hides_orig_column_without_converted_rows(app, capture, df):
    app.show_recent_transactions(df)
    assert not capture.errors
    assert "💱 原幣" not in capture.frames[0].columns


def test_recent_transactions_column_follows_the_frame_passed(app, capture, df_fx):
    """A period slice without converted rows gets no 原幣 column even though the full df has some."""
    slice_ = df_fx[df_fx["currency"] == ""]
    app.show_recent_transactions(slice_)
    assert "💱 原幣" not in capture.frames[0].columns


def test_recent_transactions_legacy_frame_renders(app, capture, legacy_df):
    app.show_recent_transactions(legacy_df)        # must not raise KeyError
    assert not capture.errors, capture.errors
    shown = capture.frames[0]
    assert "💱 原幣" not in shown.columns
    assert len(shown) == 15


def test_orig_labels_legacy_and_empty(app, legacy_df):
    assert (app.orig_labels(legacy_df) == "").all()
    assert app.orig_labels(pd.DataFrame()).empty


# ---------------------------------------------------------------------------
# End-to-end: app.main() with the injected frames (AppTest, stubs from conftest)
# ---------------------------------------------------------------------------

def _exceptions(at):
    return [str(e) for e in at.exception]


def test_apptest_dashboard_with_converted_rows(app_test, patch_load_expense_data, df, no_network):
    frame = _inject_converted_rows(df)
    at = app_test()
    patch_load_expense_data(frame)
    at.run()
    assert not at.exception, _exceptions(at)
    tables = [d.value for d in at.dataframe]
    assert any("💱 原幣" in t.columns for t in tables), [list(t.columns) for t in tables]
    texts = [m.value for m in at.markdown]
    assert any("已換算外幣**: 3 筆" in t for t in texts), texts[:20]
    assert any("換算不一致**: 1 筆" in t for t in texts)
    assert no_network.calls == []


def test_apptest_dashboard_legacy_frame_no_keyerror(app_test, patch_load_expense_data, legacy_df, no_network):
    """G15: a last_good_df without the FX columns renders every tab without error."""
    at = app_test()
    patch_load_expense_data(legacy_df)
    at.run()
    assert not at.exception, _exceptions(at)
    assert "總支出" in [m.label for m in at.metric]
    tables = [d.value for d in at.dataframe]
    assert tables and not any("💱 原幣" in t.columns for t in tables)
    assert no_network.calls == []
