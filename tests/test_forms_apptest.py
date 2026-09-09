"""
Plan §5 steps 3 and 4 — AppTest coverage of the 💱 外幣換算 card in the
新增 and 編輯 forms (input_forms.py).

Stubs: fake SheetsAPI over an in-memory migrated worksheet (conftest),
``fx.get_quote`` monkeypatched to a fixed Quote (records every call),
``auth.get_current_user`` patched, every ``requests`` call blocked.

``st.rerun`` is a no-op inside these runs: AppTest keeps the stale element
tree of the pre-rerun pass, so the explicit ``at.run()`` after a save plays
the role of the post-save rerun (same trick as the review harness).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import streamlit
from streamlit.testing.v1 import AppTest

from conftest import FX_HEADERS, REQUIRED_HEADERS, make_fake_api, make_fake_ws

import fx
import input_forms
from helpers import now_local, q6, to_twd, today_local

REAL_GET_QUOTE = fx.get_quote          # captured before any fixture stubs it
SGD_MID = Decimal("24.908000")
JPY_MID = Decimal("0.203500")
MID = {"SGD": SGD_MID, "JPY": JPY_MID, "MYR": Decimal("7.790000"), "AUD": Decimal("22.770000")}
TODAY = today_local()


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def _mdy(d: date) -> str:
    return d.strftime("%m/%d/%Y")


ROWS = {
    # description -> row (dates relative to today so the 50-newest window holds them)
    "legacy_sg": [_mdy(TODAY), "✈️ 旅行", "🍽️ 飲食", "313", "菇菇", "海南雞飯", "新加坡", "新加坡", "", "", "", ""],
    "converted_sg": [_mdy(TODAY), "✈️ 旅行", "🍽️ 飲食", "311", "過兒", "咖啡", "新加坡", "新加坡", "", "SGD", "12.50", "24.908"],
    "jpy": [_mdy(TODAY), "✈️ 旅行", "🏨 住宿", "40700", "菇菇", "飯店", "日本", "九州", "", "JPY", "200000", "0.2035"],
    "blank_country": [_mdy(TODAY), "📅 日常", "🍽️ 飲食", "120", "過兒", "無國家", "", "", "", "", "", ""],
}
ROW_NO = {name: i + 2 for i, name in enumerate(ROWS)}   # header is sheet row 1


def _add_script(df):
    import input_forms
    input_forms.expense_input_form(df)


def _edit_script(df):
    import input_forms
    input_forms.edit_expense_form(df)


@pytest.fixture
def quote_calls(monkeypatch):
    """fx.get_quote -> fixed live Quote; every call recorded as (currency, on_date)."""
    class Calls(list):
        """(currency, on_date) per call; .allow_network records the flag."""

    calls = Calls()
    calls.allow_network = []

    def fake_get_quote(currency, on_date=None, df=None, allow_network=True):
        calls.append((currency, on_date))
        calls.allow_network.append(allow_network)
        return fx.Quote(currency, MID.get(currency, Decimal("1.000000")), TODAY,
                        "frankfurter", "live", now_local())

    monkeypatch.setattr(fx, "get_quote", fake_get_quote)
    return calls


@pytest.fixture
def no_rerun(monkeypatch):
    monkeypatch.setattr(streamlit, "rerun", lambda *a, **k: None)


@pytest.fixture
def harness(monkeypatch, patch_sheets_api, patch_current_user, quote_calls, no_rerun):
    """
    Factory: ``harness(mode="add"|"edit", migrated=True, rows=())`` -> (AppTest, api).
    The worksheet carries the FX headers unless ``migrated=False``.
    """
    def _make(mode="add", migrated=True, rows=(), user="菇菇"):
        header = REQUIRED_HEADERS + FX_HEADERS if migrated else list(REQUIRED_HEADERS)
        body = [list(r)[:len(header)] for r in rows]
        ws = make_fake_ws(header, body)
        api = make_fake_api(ws)
        patch_sheets_api(api)
        patch_current_user(user)
        df = api._load_from_api()
        script = _add_script if mode == "add" else _edit_script
        at = AppTest.from_function(script, kwargs={"df": df}, default_timeout=30)
        at.run()
        assert not at.exception, [str(e) for e in at.exception]
        return at, api
    return _make


def _run(at):
    at.run()
    assert not at.exception, [str(e) for e in at.exception]
    return at


def _click(at, label):
    [b for b in at.button if b.label == label][0].click()
    return _run(at)


def _keys(at):
    return set(str(k) for k in at.session_state.filtered_state.keys())


def _ni_keys(at):
    return [n.key for n in at.number_input]


def _errors(at):
    return [e.value for e in at.error]


def _fill_add(at, gen=0, description="咖啡"):
    at.text_input(key=f"add_description_{gen}").set_value(description)
    return at


def _select_row(at, row_no):
    at.selectbox(key="edit_g0_record_select").set_value(row_no)
    return _run(at)


# ---------------------------------------------------------------------------
# Step 3 — add form
# ---------------------------------------------------------------------------

def test_taiwan_default_has_no_fx_widgets_and_no_quote(harness, quote_calls, no_network):
    """§2.1 domestic path: zero new widgets (no 幣別 selectbox either), zero network."""
    at, api = harness("add")
    assert [s.key for s in at.selectbox] == [
        "add_type_1", "add_category", "add_country", "add_location_台灣", "add_account_0",
    ]
    assert not [k for k in _keys(at) if "currency" in k or k.startswith("add_fx_")]
    assert _ni_keys(at) == ["add_amount_0"]
    assert len(at.metric) == 0 and len(at.toggle) == 0 and len(at.expander) == 0
    assert quote_calls == []
    assert no_network.calls == []

    # a TWD entry still saves exactly as before, with blank FX cells
    at.number_input(key="add_amount_0").set_value(120)
    _fill_add(at, description="便當")
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[3] == 120 and row[9:12] == ["", "", ""]
    assert quote_calls == []


def test_singapore_defaults_to_sgd_and_converts(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    assert at.selectbox(key="add_currency_新加坡").value == "SGD"
    assert quote_calls and quote_calls[0] == ("SGD", TODAY)
    # first-use hint until an amount is typed
    assert input_forms.FX_HELP_FIRST_USE in [c.value for c in at.caption]

    at.number_input(key="add_fx_amount_0").set_value(12.5)
    _run(at)
    assert "add_amount_0" not in _ni_keys(at)                  # in-form 金額 replaced
    expected = to_twd(Decimal("12.5"), SGD_MID, 2)
    assert [m.value for m in at.metric] == [f"NT${expected:,}"]
    assert any(v.startswith(f"金額 (TWD)：NT${expected:,} ← SGD 12.50 × 24.908") for v in [i.value for i in at.info])
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert caption.startswith("匯率 24.908 · ✅ 今日匯率 · Frankfurter")
    assert "含手續費" not in caption

    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[3] == expected
    assert row[9:12] == ["SGD", "12.50", "24.908"]
    assert row[6:8] == ["新加坡", "新加坡"]
    _run(at)                                                  # the post-save rerun
    assert f"✅ 成功新增支出: 咖啡 - SGD 12.50 ≈ NT${expected:,}" in [s.value for s in at.success]


def test_after_save_amount_key_cleared_rate_kept_fee_off_for_new_country(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    at.number_input(key="add_fx_amount_0").set_value(12.5)
    _run(at)
    at.toggle(key="add_fx_fee_新加坡").set_value(True)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    _run(at)
    keys = _keys(at)
    assert "add_fx_amount_0" not in keys and "add_fx_amount_1" in keys
    assert at.number_input(key="add_fx_amount_1").value is None
    assert f"add_fx_rate_SGD_{TODAY.isoformat()}" in keys       # persists for the trip
    assert at.toggle(key="add_fx_fee_新加坡").value is True      # persists per country
    assert at.selectbox(key="add_currency_新加坡").value == "SGD"

    at.selectbox(key="add_country").set_value("馬來西亞")
    _run(at)
    assert at.selectbox(key="add_currency_馬來西亞").value == "MYR"
    assert at.toggle(key="add_fx_fee_馬來西亞").value is False    # G15: never inherited
    assert f"add_fx_rate_MYR_{TODAY.isoformat()}" in _ni_keys(at)


def test_fee_toggle_folds_into_stored_rate(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    at.number_input(key="add_fx_amount_0").set_value(12.5)
    at.toggle(key="add_fx_fee_新加坡").set_value(True)
    _run(at)
    rate_eff = q6(SGD_MID * Decimal("1.015"))
    expected = to_twd(Decimal("12.5"), rate_eff, 2)
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert caption.startswith("匯率 25.28162（含手續費）")
    # the widget itself still shows the mid-market rate (never re-seeded)
    assert at.number_input(key=f"add_fx_rate_SGD_{TODAY.isoformat()}").value == float(SGD_MID)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[11] == "25.28162" and Decimal(row[11]) == rate_eff
    assert row[3] == expected == to_twd(Decimal(row[10]), Decimal(row[11]), 2)


def test_manual_rate_override_and_refresh(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    rate_key = f"add_fx_rate_SGD_{TODAY.isoformat()}"
    at.number_input(key="add_fx_amount_0").set_value(10)
    at.number_input(key=rate_key).set_value(25.0)
    _run(at)
    assert [m.value for m in at.metric] == ["NT$250"]
    n = len(quote_calls)
    at.button(key="add_fx_refresh").click()
    _run(at)
    assert len(quote_calls) > n                                 # cache invalidated -> refetched
    assert at.number_input(key=rate_key).value == float(SGD_MID)  # re-seeded from the quote
    assert [m.value for m in at.metric] == [f"NT${to_twd(10, SGD_MID)}"]


def test_back_to_taiwan_drops_the_card_again(harness, quote_calls):
    """Regression: the 幣別 selectbox is per-country; 新加坡 -> 台灣 leaves zero FX widgets."""
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    assert "add_currency_新加坡" in [s.key for s in at.selectbox]
    at.selectbox(key="add_country").set_value("台灣")
    _run(at)
    assert not [s.key for s in at.selectbox if "currency" in s.key]
    assert _ni_keys(at) == ["add_amount_0"]
    n = len(quote_calls)
    _run(at)
    assert len(quote_calls) == n                                # no quote on the domestic path


def test_refresh_pushes_fresh_rate_into_the_widget(harness, quote_calls):
    """
    Regression (blocker): ↻ must ASSIGN the fresh rate to the widget key so the
    browser adopts it (proto.set_value). With a bare ``del`` the frontend kept the
    override and the save used it while the preview showed the fresh rate.
    The stale value is re-sent together with the click, as a real frontend does.
    """
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    rate_key = f"add_fx_rate_SGD_{TODAY.isoformat()}"
    at.number_input(key="add_fx_amount_0").set_value(10)
    at.number_input(key=rate_key).set_value(30.0)
    _run(at)
    assert [m.value for m in at.metric] == ["NT$300"]

    at.number_input(key=rate_key).set_value(30.0)               # frontend retention
    at.button(key="add_fx_refresh").click()
    _run(at)
    widget = at.number_input(key=rate_key)
    assert widget.value == float(SGD_MID)
    assert widget.proto.set_value is True                        # pushed to the frontend
    assert widget.proto.value == float(SGD_MID)
    assert [m.value for m in at.metric] == ["NT$249"]
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert caption.startswith("匯率 24.908 · ✅ 今日匯率")           # the callback's live quote, not 🕒
    assert "add_fx_fresh_quote_0" not in _keys(at)                # consumed once

    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[3] == 249 and row[9:12] == ["SGD", "10.00", "24.908"]
    _run(at)
    assert "✅ 成功新增支出: 咖啡 - SGD 10.00 ≈ NT$249" in [s.value for s in at.success]


def test_currency_twd_abroad_restores_plain_amount(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    at.selectbox(key="add_currency_新加坡").set_value("TWD")
    _run(at)
    assert "add_amount_0" in _ni_keys(at)
    assert "add_fx_amount_0" not in _keys(at)
    at.number_input(key="add_amount_0").set_value(300)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[3] == 300 and row[6] == "新加坡" and row[9:12] == ["", "", ""]


def test_validation_messages(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    assert "請輸入原幣金額" in _errors(at)
    assert api.worksheet.data_rows() == []

    at.number_input(key="add_fx_amount_0").set_value(5)
    at.number_input(key=f"add_fx_rate_SGD_{TODAY.isoformat()}").set_value(0.0)
    _click(at, "💾 儲存支出")
    assert "匯率無效" in _errors(at)
    assert api.worksheet.data_rows() == []


def test_duplicate_guard_uses_orig_amount(harness, quote_calls):
    """Two SGD amounts rounding to the same NT$ are both accepted; an identical entry is refused."""
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    at.number_input(key="add_fx_amount_0").set_value(1.0)
    _fill_add(at, 0)
    _click(at, "💾 儲存支出")
    _run(at)
    assert len(api.worksheet.data_rows()) == 1
    assert to_twd(Decimal("1.00"), SGD_MID) == to_twd(Decimal("1.01"), SGD_MID) == 25

    at.number_input(key="add_fx_amount_1").set_value(1.01)
    _fill_add(at, 1)
    _click(at, "💾 儲存支出")
    _run(at)
    assert len(api.worksheet.data_rows()) == 2                  # same NT$25, different SGD

    at.number_input(key="add_fx_amount_2").set_value(1.01)
    _fill_add(at, 2)
    _click(at, "💾 儲存支出")
    assert "⚠️ 相同的支出剛剛已儲存，請勿重複提交" in [w.value for w in at.warning]
    assert len(api.worksheet.data_rows()) == 2


def test_chain_failure_static_caption_and_save(harness, monkeypatch, no_network):
    """requests raising -> real get_quote falls through to the static tier; save still works."""
    at, api = harness("add")
    monkeypatch.setattr(fx, "get_quote", REAL_GET_QUOTE)            # undo the fixture stub
    try:
        fx._fx_store.clear()                                       # drop quotes cached by other tests
    except Exception:
        pass
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    assert no_network.calls, "the chain should have tried the endpoints"
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert "⚠️ 離線匯率" in caption
    at.number_input(key="add_fx_amount_0").set_value(12.5)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[9] == "SGD" and row[10] == "12.50"
    assert row[3] == to_twd(Decimal("12.5"), Decimal(row[11]), 2)


def test_unmigrated_sheet_warns_before_and_after(harness, quote_calls):
    at, api = harness("add", migrated=False)
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    assert input_forms.FX_MISSING_COLUMNS_CAPTION in [c.value for c in at.caption]
    at.number_input(key="add_fx_amount_0").set_value(12.5)
    _fill_add(at)
    _click(at, "💾 儲存支出")
    row = api.worksheet.data_rows()[-1]
    assert row[3] == to_twd(Decimal("12.5"), SGD_MID, 2)
    assert all(cell == "" for cell in row[9:])                  # FX fields dropped, TWD row written
    assert api.last_write_warnings
    _run(at)
    warnings = [w.value for w in at.warning]
    assert input_forms.FX_DROPPED_WARNING in warnings
    assert any("幣別" in w and "已略過" in w for w in warnings)


def test_add_form_quotes_today_not_form_date(harness, quote_calls):
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("日本")
    _run(at)
    assert at.selectbox(key="add_currency_日本").value == "JPY"
    assert all(d == TODAY for _, d in quote_calls)
    # JPY: 0 decimals, step 1
    at.number_input(key="add_fx_amount_0").set_value(1500)
    _run(at)
    assert [m.value for m in at.metric] == [f"NT${to_twd(1500, JPY_MID, 0)}"]
    infos = [i.value for i in at.info]
    assert any("JPY 1,500 × 0.2035" in v for v in infos)


# ---------------------------------------------------------------------------
# Step 4 — edit form
# ---------------------------------------------------------------------------

def _edit(harness, rows=None):
    return harness("edit", rows=list(ROWS.values()) if rows is None else rows)


def test_record_label_suffix_for_converted_rows(harness, quote_calls):
    at, api = _edit(harness)
    labels = at.selectbox(key="edit_g0_record_select").format_func
    options = at.selectbox(key="edit_g0_record_select").options
    rendered = [labels(o) if callable(labels) else o for o in options]
    text = " | ".join(str(r) for r in rendered)
    assert "咖啡 - NT$311 · SGD 12.50" in text
    assert "飯店 - NT$40,700 · JPY 200,000" in text
    assert "海南雞飯 - NT$313 (#row" in text                     # legacy row: no suffix


def test_legacy_singapore_row_opens_plain(harness, quote_calls):
    """G4: blank stored currency -> 金額 widget present, no FX keys, no quote."""
    at, api = _edit(harness)
    _select_row(at, ROW_NO["legacy_sg"])
    row = ROW_NO["legacy_sg"]
    assert at.checkbox(key=f"edit_g0_fx_optin_{row}").value is False
    assert f"edit_g0_amount_{row}" in _ni_keys(at)
    assert at.number_input(key=f"edit_g0_amount_{row}").value == 313.0
    fx_keys = [k for k in _keys(at) if ("_fx_" in k and "optin" not in k) or "_currency_" in k]
    assert fx_keys == []
    assert quote_calls == []

    # plain update: no FX keys in updated_data, FX cells untouched
    at.number_input(key=f"edit_g0_amount_{row}").set_value(320.0)
    _click(at, "💾 更新")
    upd = [c for c in api.worksheet.calls if c[0] == "update"][-1]
    written = upd[2]["values"][0]
    assert written[3] == 320 and written[9:12] == ["", "", ""]


def test_blank_country_row_does_not_raise(harness, quote_calls):
    at, api = _edit(harness)
    _select_row(at, ROW_NO["blank_country"])
    row = ROW_NO["blank_country"]
    assert at.selectbox(key=f"edit_g0_{row}_country").value == ""
    # opting in on a blank-country row defaults to TWD (COUNTRY_CURRENCY.get) -> still no card
    at.checkbox(key=f"edit_g0_fx_optin_{row}").check()
    _run(at)
    assert at.selectbox(key=f"edit_g0_currency_{row}").value == "TWD"
    assert f"edit_g0_amount_{row}" in _ni_keys(at)
    assert quote_calls == []


def test_converted_row_prefills_card_and_hides_amount(harness, quote_calls):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    assert at.checkbox(key=f"edit_g0_fx_optin_{row}").value is True
    assert at.selectbox(key=f"edit_g0_currency_{row}").value == "SGD"
    assert at.number_input(key=f"edit_g0_fx_amount_{row}").value == 12.5
    assert at.number_input(key=f"edit_g0_fx_rate_{row}_SGD").value == 24.908
    assert f"edit_g0_amount_{row}" not in _ni_keys(at)          # 金額 hidden
    assert any("NT$311 ← SGD 12.50 × 24.908" in i.value for i in at.info)
    assert quote_calls == []                                     # stored rate seeds the widget: no fetch


def test_untouched_card_always_writes_fx_keys(harness, quote_calls):
    """§2.5: the card shown -> the three FX cells are re-written explicitly (same values)."""
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    at.text_input(key=f"edit_g0_description_{row}").set_value("咖啡 (改)")
    _click(at, "💾 更新")
    upd = [c for c in api.worksheet.calls if c[0] == "update"][-1]
    written = upd[2]["values"][0]
    assert written[5] == "咖啡 (改)" and written[3] == 311
    assert written[9:12] == ["SGD", "12.50", "24.908"]


def test_untouched_card_updated_data_carries_fx_keys(harness, quote_calls, monkeypatch):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    seen = {}
    real_update = api.update_expense

    def spy(sheet_row, original, updated):
        seen["updated"] = dict(updated)
        seen["original"] = dict(original)
        return real_update(sheet_row, original, updated)
    monkeypatch.setattr(api, "update_expense", spy)
    at.text_input(key=f"edit_g0_notes_{row}").set_value("n")
    _click(at, "💾 更新")
    assert seen["updated"]["amount"] == 311.0
    assert seen["updated"]["currency"] == "SGD"
    assert seen["updated"]["orig_amount"] == "12.50"
    assert seen["updated"]["fx_rate"] == "24.908000"
    assert seen["original"]["currency"] == "SGD"
    assert seen["original"]["orig_amount"] == 12.5 and seen["original"]["fx_rate"] == 24.908


INCONSISTENT_SG = [_mdy(TODAY), "✈️ 旅行", "🍽️ 飲食", "999", "過兒", "不一致",
                   "新加坡", "新加坡", "", "SGD", "10.00", "24.908"]


def test_edit_inconsistent_row_untouched_update_writes_displayed_amount(harness, quote_calls, monkeypatch):
    """
    Regression (repair round 2): a row whose 金額 (999) disagrees with
    to_twd(orig, rate) (249) -- exactly what the §2.6 audit flags -- must be
    repaired by opening it in 編輯 and pressing 更新 without touching the card:
    the in-form info, the saved 金額 and the flash all say NT$249.
    """
    at, api = _edit(harness, rows=[INCONSISTENT_SG])
    row = 2
    _select_row(at, row)
    assert any("NT$249 ← SGD 10.00 × 24.908" in i.value for i in at.info)
    seen = {}
    real_update = api.update_expense

    def spy(sheet_row, original, updated):
        seen["updated"] = dict(updated)
        return real_update(sheet_row, original, updated)
    monkeypatch.setattr(api, "update_expense", spy)
    _click(at, "💾 更新")
    assert seen["updated"]["amount"] == 249.0
    assert seen["updated"]["currency"] == "SGD"
    assert seen["updated"]["orig_amount"] == "10.00"
    assert seen["updated"]["fx_rate"] == "24.908000"
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == 249 == to_twd(Decimal("10.00"), Decimal("24.908"))
    assert written[9:12] == ["SGD", "10.00", "24.908"]
    flashes = [v.value for v in at.success] + [
        str(at.session_state["edit_expense_flash"]) if "edit_expense_flash" in at.session_state else ""]
    assert any("≈ NT$249" in f for f in flashes) and not any("999" in f for f in flashes)
    assert quote_calls == []                                     # stored rate; the quote is never consulted


def test_changed_orig_amount_recomputes_from_stored_rate(harness, quote_calls):
    """Rule (iii): 金額 = to_twd(orig, stored 6-dp rate); the quote is never consulted."""
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    at.number_input(key=f"edit_g0_fx_amount_{row}").set_value(20.0)
    _run(at)
    assert [m.value for m in at.metric] == [f"NT${to_twd(20, Decimal('24.908'))}"]
    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == to_twd(20, Decimal("24.908")) == 498
    assert written[9:12] == ["SGD", "20.00", "24.908"]
    assert quote_calls == []


def test_statement_amount_derives_rate(harness, quote_calls):
    """帳單金額 41,013 on JPY 200,000 -> rate 0.205065, invariant within ±1 (G3)."""
    at, api = _edit(harness)
    row = ROW_NO["jpy"]
    _select_row(at, row)
    at.number_input(key=f"edit_g0_stmt_{row}").set_value(41013)
    _run(at)
    assert [m.value for m in at.metric] == ["NT$41,013"]
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert caption.startswith("匯率 0.205065") and "帳單" in caption
    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[9:12] == ["JPY", "200000", "0.205065"]
    assert written[3] == 41013
    assert abs(written[3] - to_twd(Decimal(written[10]), Decimal(written[11]), 0)) <= 1


def test_backfill_keeps_twd_amount_and_derives_rate(harness, quote_calls):
    """Legacy row + opt-in: 保留原台幣金額 defaults ON; 金額 stays, rate = 金額 / orig."""
    at, api = _edit(harness)
    row = ROW_NO["legacy_sg"]
    _select_row(at, row)
    at.checkbox(key=f"edit_g0_fx_optin_{row}").check()
    _run(at)
    assert at.selectbox(key=f"edit_g0_currency_{row}").value == "SGD"   # from 國家 when nothing stored
    assert at.checkbox(key=f"edit_g0_keep_twd_{row}").value is True
    assert quote_calls and quote_calls[0][0] == "SGD"            # no stored rate -> quote for the row date
    assert quote_calls[0][1] == TODAY
    at.number_input(key=f"edit_g0_fx_amount_{row}").set_value(12.5)
    _run(at)
    assert [m.value for m in at.metric] == ["NT$313"]
    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == 313                                     # totals never move
    assert written[9:11] == ["SGD", "12.50"]
    assert Decimal(written[11]) == q6(Decimal(313) / Decimal("12.5")) == Decimal("25.04")


def test_backfill_without_keep_uses_quote(harness, quote_calls):
    at, api = _edit(harness)
    row = ROW_NO["legacy_sg"]
    _select_row(at, row)
    at.checkbox(key=f"edit_g0_fx_optin_{row}").check()
    _run(at)
    at.checkbox(key=f"edit_g0_keep_twd_{row}").uncheck()
    at.number_input(key=f"edit_g0_fx_amount_{row}").set_value(12.5)
    _run(at)
    expected = to_twd(Decimal("12.5"), SGD_MID, 2)
    assert [m.value for m in at.metric] == [f"NT${expected}"]
    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == expected and written[9:12] == ["SGD", "12.50", "24.908"]


def test_currency_to_twd_writes_explicit_blanks(harness, quote_calls, monkeypatch):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    seen = {}
    real_update = api.update_expense

    def spy(sheet_row, original, updated):
        seen["updated"] = dict(updated)
        return real_update(sheet_row, original, updated)
    monkeypatch.setattr(api, "update_expense", spy)

    at.selectbox(key=f"edit_g0_currency_{row}").set_value("TWD")
    _run(at)
    assert f"edit_g0_amount_{row}" in _ni_keys(at)              # plain 金額 returns
    assert at.number_input(key=f"edit_g0_amount_{row}").value == 311.0
    at.number_input(key=f"edit_g0_amount_{row}").set_value(350.0)
    _click(at, "💾 更新")
    assert seen["updated"]["currency"] == "" and seen["updated"]["orig_amount"] == "" and seen["updated"]["fx_rate"] == ""
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == 350 and written[9:12] == ["", "", ""]


def test_optin_unticked_on_converted_row_also_blanks(harness, quote_calls):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    at.checkbox(key=f"edit_g0_fx_optin_{row}").uncheck()
    _run(at)
    assert f"edit_g0_amount_{row}" in _ni_keys(at)
    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == 311 and written[9:12] == ["", "", ""]


def test_edit_validation_and_refresh(harness, quote_calls):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    at.number_input(key=f"edit_g0_fx_amount_{row}").set_value(0.0)
    _click(at, "💾 更新")
    assert "請輸入原幣金額" in _errors(at)
    assert not [c for c in api.worksheet.calls if c[0] == "update"]

    # ↻ on a converted row: quote fetched for the ROW date and the rate re-seeded from it
    at.button(key=f"edit_g0_fx_refresh_{row}").click()
    _run(at)
    assert quote_calls and quote_calls[-1] == ("SGD", TODAY)
    assert at.number_input(key=f"edit_g0_fx_rate_{row}_SGD").value == float(SGD_MID)


def test_edit_refresh_pushes_fresh_rate_and_update_uses_it(harness, quote_calls):
    """Regression (blocker, 編輯): stored 32 -> ↻ -> widget 24.908 with set_value; 更新 writes @ 24.908."""
    rows = list(ROWS.values())
    rows[list(ROWS).index("converted_sg")] = (
        [_mdy(TODAY), "✈️ 旅行", "🍽️ 飲食", "400", "過兒", "咖啡", "新加坡", "新加坡", "", "SGD", "12.50", "32"])
    at, api = harness("edit", rows=rows)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    rate_key = f"edit_g0_fx_rate_{row}_SGD"
    assert at.number_input(key=rate_key).value == 32.0
    assert quote_calls == []

    at.number_input(key=rate_key).set_value(32.0)               # frontend retention
    at.button(key=f"edit_g0_fx_refresh_{row}").click()
    _run(at)
    assert quote_calls and quote_calls[-1] == ("SGD", TODAY)
    widget = at.number_input(key=rate_key)
    assert widget.value == float(SGD_MID) and widget.proto.set_value is True
    assert [m.value for m in at.metric] == ["NT$311"]
    caption = [c.value for c in at.caption if c.value.startswith("匯率")][0]
    assert caption.startswith("匯率 24.908 · ✅ 今日匯率")

    _click(at, "💾 更新")
    written = [c for c in api.worksheet.calls if c[0] == "update"][-1][2]["values"][0]
    assert written[3] == 311 and written[9:12] == ["SGD", "12.50", "24.908"]


def test_domestic_foreign_purchase_via_edit_optin(harness, quote_calls):
    """A USD purchase at home is entered through the 編輯 opt-in card (國家 stays 台灣)."""
    tw = [_mdy(TODAY), "📅 日常", "🛍️ 購物", "1600", "菇菇", "網購", "台灣", "台北市", "", "", "", ""]
    at, api = harness("edit", rows=[tw])
    _select_row(at, 2)
    assert f"edit_g0_amount_2" in _ni_keys(at) and quote_calls == []
    at.checkbox(key="edit_g0_fx_optin_2").check()
    _run(at)
    assert at.selectbox(key="edit_g0_currency_2").value == "TWD"   # 台灣 -> still no card
    assert quote_calls == []
    at.selectbox(key="edit_g0_currency_2").set_value("USD")
    _run(at)
    assert quote_calls and quote_calls[-1][0] == "USD"
    assert "edit_g0_fx_amount_2" in _ni_keys(at) and "edit_g0_amount_2" not in _ni_keys(at)


def test_edit_generation_bump_clears_fx_keys(harness, quote_calls):
    at, api = _edit(harness)
    row = ROW_NO["converted_sg"]
    _select_row(at, row)
    at.number_input(key=f"edit_g0_fx_amount_{row}").set_value(20.0)
    _click(at, "💾 更新")
    _run(at)
    assert not [k for k in _keys(at) if k.startswith("edit_g0_")]
    assert at.session_state["edit_form_gen"] == 1


def test_plain_rerun_with_foreign_country_does_not_fetch(harness, quote_calls, no_network):
    """
    Streamlit re-renders every tab on every interaction. With 國家 left on a
    foreign country from a past trip, an unrelated click elsewhere in the app
    must not put the rate chain on the critical path — that is what made the app
    feel like it could not connect.
    """
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    assert quote_calls, "picking a country is a deliberate ask: it should fetch"
    assert quote_calls.allow_network[-1] is True

    before = len(quote_calls)
    for _ in range(3):                      # stand-ins for unrelated reruns
        _run(at)
    assert all(flag is False for flag in quote_calls.allow_network[before:]), (
        "a plain rerun asked to go to the network")


def test_typing_an_amount_fetches(harness, quote_calls, no_network):
    """Once an amount is being converted the rate is genuinely needed."""
    at, api = harness("add")
    at.selectbox(key="add_country").set_value("新加坡")
    _run(at)
    at.number_input(key="add_fx_amount_0").set_value(12.5)
    _run(at)
    assert quote_calls.allow_network[-1] is True
