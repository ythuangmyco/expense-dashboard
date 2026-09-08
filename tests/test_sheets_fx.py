"""
Plan §5 step 2a — sheets_api.py tolerates the optional FX columns (幣別/原幣金額/匯率).

No Google Sheet, no network: an in-memory fake worksheet stands in for gspread and
`requests.get` is monkeypatched for the CSV path. Run with
    expense_env/bin/python -m pytest -q tests/test_sheets_fx.py
"""

import os
import random
import sys
import types
from decimal import Decimal
from io import StringIO

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import sheets_api  # noqa: E402
from sheets_api import SheetsAPI, EXPECTED_HEADERS, EXPECTED_COLUMNS  # noqa: E402
from config import OPTIONAL_HEADERS, WORKSHEET_GID, SHEET_ID, SHEET_URL, COLUMN_MAPPING  # noqa: E402
from helpers import parse_amount  # noqa: E402

SNAPSHOT = os.path.join(ROOT, "new_to_fill.csv")
FX_HEADERS = EXPECTED_HEADERS + OPTIONAL_HEADERS  # 12 columns

ROW_TWD = ['03/31/2026', '📅 日常', '🧴 日用', '240', '菇菇', '印章', '台灣', '臺南', '']
ROW_SGD = ['09/06/2026', '✈️ 旅行', '🍽️ 飲食', '316', '過兒', '咖啡', '新加坡', '新加坡', '',
           'SGD', '12.50', '25.2816']


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeWorksheet:
    """Minimal gspread.Worksheet stand-in: rows are lists of str, 1-based like the API."""

    def __init__(self, rows, grid_width=26):
        self.rows = [list(r) for r in rows]
        self.grid_width = grid_width
        self.calls = {"row_values": [], "get_all_values": 0, "append_row": [],
                      "update": [], "delete_rows": []}

    def _width(self):
        return max([len(r) for r in self.rows] + [0])

    def row_values(self, n):
        self.calls["row_values"].append(n)
        if n < 1 or n > len(self.rows):
            return []
        row = list(self.rows[n - 1])
        while row and row[-1] == '':          # gspread trims trailing blanks
            row.pop()
        return row

    def get_all_values(self):
        self.calls["get_all_values"] += 1
        w = self._width()
        return [list(r) + [''] * (w - len(r)) for r in self.rows]

    def append_row(self, values, **kwargs):
        self.calls["append_row"].append(list(values))
        self.rows.append([str(v) if v != '' else '' for v in values])

    def update(self, values=None, range_name=None, **kwargs):
        self.calls["update"].append((range_name, [list(v) for v in values]))
        start, end = range_name.split(':')
        row_no = int(''.join(ch for ch in start if ch.isdigit()))
        self.rows[row_no - 1] = [str(v) if v != '' else '' for v in values[0]]

    def delete_rows(self, n, *args, **kwargs):
        self.calls["delete_rows"].append(n)
        del self.rows[n - 1]


class FakeSt(types.SimpleNamespace):
    """Streamlit stand-in capturing messages; `secrets` is a plain dict."""

    def __init__(self, secrets=None):
        super().__init__()
        self.secrets = secrets if secrets is not None else {}
        self.errors, self.infos, self.warnings = [], [], []
        self.session_state = {}
        self.cache_data = types.SimpleNamespace(clear=lambda: None)

    def error(self, msg, *a, **k):
        self.errors.append(str(msg))

    def info(self, msg, *a, **k):
        self.infos.append(str(msg))

    def warning(self, msg, *a, **k):
        self.warnings.append(str(msg))


@pytest.fixture
def fake_st(monkeypatch):
    st = FakeSt()
    monkeypatch.setattr(sheets_api, "st", st)
    return st


def make_api(ws, fake_st):
    """A SheetsAPI wired to the fake worksheet (constructor sees no credentials)."""
    api = SheetsAPI()
    assert api.worksheet is None and api.read_only
    api.worksheet = ws
    api.api_available = True
    api.read_only = False
    return api


def fake_requests_get(monkeypatch, text: str):
    class Resp:
        status_code = 200
        headers = {'content-type': 'text/csv'}
        content = text.encode('utf-8')

        def raise_for_status(self):
            pass

    captured = {}

    def _get(url, *a, **k):
        captured['url'] = url
        return Resp()

    monkeypatch.setattr(sheets_api.requests, "get", _get)
    return captured


# ---------------------------------------------------------------------------
# GID resolution
# ---------------------------------------------------------------------------

def test_resolve_worksheet_gid_defaults_to_config(fake_st):
    assert sheets_api._resolve_worksheet_gid() == WORKSHEET_GID


def test_resolve_worksheet_gid_honours_secret(fake_st):
    fake_st.secrets = {"app": {"sheet_id": "copy-id", "worksheet_gid": 1290819173}}
    assert sheets_api._resolve_worksheet_gid() == 1290819173
    fake_st.secrets = {"app": {"worksheet_gid": "1290819173"}}   # TOML string also accepted
    assert sheets_api._resolve_worksheet_gid() == 1290819173
    fake_st.secrets = {"app": {"sheet_id": "x"}}                  # key absent -> config
    assert sheets_api._resolve_worksheet_gid() == WORKSHEET_GID


def test_csv_url_uses_secret_gid(fake_st, monkeypatch):
    fake_st.secrets = {"app": {"sheet_id": SHEET_ID, "worksheet_gid": 1290819173}}
    api = SheetsAPI()
    captured = fake_requests_get(monkeypatch, ",".join(EXPECTED_HEADERS) + "\n" + ",".join(ROW_TWD) + "\n")
    api._load_from_csv()
    assert captured['url'].endswith("gid=1290819173") and SHEET_ID in captured['url']


def test_csv_url_unchanged_without_override(fake_st, monkeypatch):
    api = SheetsAPI()
    captured = fake_requests_get(monkeypatch, ",".join(EXPECTED_HEADERS) + "\n" + ",".join(ROW_TWD) + "\n")
    api._load_from_csv()
    assert captured['url'] == SHEET_URL


def test_get_status_reports_resolved_gid(fake_st):
    fake_st.secrets = {"app": {"worksheet_gid": 1290819173}}
    assert SheetsAPI().get_status()["worksheet_gid"] == 1290819173


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _snapshot_text():
    with open(SNAPSHOT, encoding='utf-8') as fh:
        return fh.read()


def test_snapshot_totals_identical_and_no_fx(fake_st, monkeypatch):
    text = _snapshot_text()
    api = SheetsAPI()
    fake_requests_get(monkeypatch, text)
    df = api._load_from_csv()

    # Reference total computed independently with the pre-FX parser on the raw cells
    raw = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False, skip_blank_lines=False)
    ref_total = sum(v for v in map(parse_amount, raw['金額'].tolist()) if v is not None)
    assert len(raw) == 1577  # the 1,577-row snapshot
    assert round(float(df['amount'].sum()), 2) == round(ref_total, 2)
    assert len(df) == len(raw)

    assert (df['currency'] == '').all()
    assert df['orig_amount'].isna().all() and df['fx_rate'].isna().all()
    assert df['orig_amount'].dtype == 'float64' and df['fx_rate'].dtype == 'float64'
    assert df.attrs['fx_headers'] is False
    assert sheets_api.has_fx_columns(df) is False
    assert set(EXPECTED_COLUMNS) <= set(df.columns)


def test_process_data_12_columns(fake_st):
    api = SheetsAPI()
    rows = [
        ROW_TWD + ['', '', ''],
        ROW_SGD,
        ['09/07/2026', '✈️ 旅行', '🍽️ 飲食', '41013', '菇菇', '拉麵', '日本', '九州', '', 'sgd', '12.5', '0.205065'],
        ['09/08/2026', '📅 日常', '🍽️ 飲食', '100', '菇菇', '便當', '台灣', '臺南', '', 'TWD', '', ''],
        ['09/08/2026', '📅 日常', '🍽️ 飲食', '200', '菇菇', '茶', '台灣', '臺南', '', 'twd', 'abc', '1,234.5'],
    ]
    df = api._process_data(pd.DataFrame(rows, columns=FX_HEADERS), source="test")
    assert list(df['currency']) == ['', 'SGD', 'SGD', '', '']
    assert df['orig_amount'].isna().iloc[0]
    assert df['orig_amount'].iloc[1] == 12.5 and df['orig_amount'].iloc[2] == 12.5
    assert df['fx_rate'].iloc[1] == 25.2816 and df['fx_rate'].iloc[2] == 0.205065
    assert df['orig_amount'].isna().iloc[4]            # unparseable -> NaN, never raises
    assert df['fx_rate'].iloc[4] == 1234.5             # thousands separator stripped
    assert list(df['amount']) == [240.0, 316.0, 41013.0, 100.0, 200.0]
    assert df['orig_amount'].dtype == 'float64' and df['fx_rate'].dtype == 'float64'
    assert sheets_api.has_fx_columns(df) is None       # _process_data alone does not stamp attrs


def test_load_from_api_stamps_attrs_and_calls_get_all_values_once(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_TWD + ['', '', ''], ROW_SGD])
    api = make_api(ws, fake_st)
    df = api._load_from_api()
    assert df.attrs['fx_headers'] is True
    assert sheets_api.has_fx_columns(df) is True
    assert list(df['currency']) == ['', 'SGD']
    assert ws.calls["get_all_values"] == 1
    assert ws.calls["row_values"] == []                # never touches the header separately (G5)

    ws9 = FakeWorksheet([EXPECTED_HEADERS, ROW_TWD])
    df9 = make_api(ws9, fake_st)._load_from_api()
    assert df9.attrs['fx_headers'] is False
    assert (df9['currency'] == '').all() and df9['orig_amount'].isna().all()
    assert ws9.calls["row_values"] == []


def test_has_fx_columns_reads_attrs_only(fake_st):
    assert sheets_api.has_fx_columns(None) is None
    assert sheets_api.has_fx_columns(sheets_api._empty_df()) is None
    legacy = pd.DataFrame({'amount': [1.0]})           # last_good_df from before deploy
    assert sheets_api.has_fx_columns(legacy) is None
    legacy.attrs['fx_headers'] = True
    assert sheets_api.has_fx_columns(legacy) is True


def test_empty_df_matches_expected_columns():
    df = sheets_api._empty_df()
    assert list(df.columns) == EXPECTED_COLUMNS
    for c in ('currency', 'orig_amount', 'fx_rate'):
        assert c in df.columns
    assert df['orig_amount'].dtype == 'float64' and df['fx_rate'].dtype == 'float64'


def test_csv_mojibake_fx_headers(fake_st, monkeypatch):
    """Latin-1 round-trip resolves mojibake FX headers to the proper-Chinese COLUMN_MAPPING keys."""
    moji = [h.encode('utf-8').decode('latin-1') for h in OPTIONAL_HEADERS]
    for m in moji:
        assert m not in COLUMN_MAPPING  # no mojibake spellings needed in config
    header = ",".join(EXPECTED_HEADERS + moji)
    text = header + "\n" + ",".join(ROW_TWD) + ",,,\n" + ",".join(ROW_SGD) + "\n"
    api = SheetsAPI()
    fake_requests_get(monkeypatch, text)
    df = api._load_from_csv()
    assert df.attrs['fx_headers'] is True
    assert list(df['currency']) == ['', 'SGD']
    assert df['orig_amount'].iloc[1] == 12.5 and df['fx_rate'].iloc[1] == 25.2816
    assert list(df['amount']) == [240.0, 316.0]


def test_csv_shuffled_columns(fake_st, monkeypatch):
    cols = list(FX_HEADERS)
    random.Random(7).shuffle(cols)
    idx = {h: i for i, h in enumerate(FX_HEADERS)}
    text = ",".join(cols) + "\n" + ",".join(ROW_SGD[idx[c]] for c in cols) + "\n"
    api = SheetsAPI()
    fake_requests_get(monkeypatch, text)
    df = api._load_from_csv()
    assert df['currency'].iloc[0] == 'SGD' and df['orig_amount'].iloc[0] == 12.5
    assert df['amount'].iloc[0] == 316.0 and df['description'].iloc[0] == '咖啡'


# ---------------------------------------------------------------------------
# _header_map
# ---------------------------------------------------------------------------

def test_header_map_9_and_12_headers_shuffled(fake_st):
    for headers in (EXPECTED_HEADERS, FX_HEADERS):
        for seed in range(3):
            cols = list(headers)
            random.Random(seed).shuffle(cols)
            ws = FakeWorksheet([cols])
            hm, width = make_api(ws, fake_st)._header_map()
            assert width == len(cols)
            for h in headers:
                assert hm[COLUMN_MAPPING[h]] == cols.index(h)
            if headers is EXPECTED_HEADERS:
                assert not any(f in hm for f in sheets_api.FX_FIELDS)
            else:
                assert all(f in hm for f in sheets_api.FX_FIELDS)
            assert ws.calls["row_values"] == [1]


def test_header_map_refuses_missing_required(fake_st):
    ws = FakeWorksheet([[h for h in EXPECTED_HEADERS if h != '帳戶'] + OPTIONAL_HEADERS])
    assert make_api(ws, fake_st)._header_map() is None
    assert fake_st.errors and '帳戶' in fake_st.errors[-1]


# ---------------------------------------------------------------------------
# _cell_value
# ---------------------------------------------------------------------------

def test_cell_value_fx_formats():
    cv = SheetsAPI._cell_value
    assert cv('fx_rate', 0.205065) == '0.205065'
    assert cv('fx_rate', '0.205065') == '0.205065'
    assert cv('fx_rate', Decimal('25.2816')) == '25.2816'
    assert cv('fx_rate', 25.0) == '25'                        # trimmed, but a str, never int()
    assert isinstance(cv('fx_rate', 25.0), str)
    assert cv('fx_rate', 0.12345678) == '0.123457'            # 6 dp half-up
    assert cv('fx_rate', 0.0000001) == '0'
    assert cv('fx_rate', '') == '' and cv('fx_rate', None) == '' and cv('fx_rate', float('nan')) == ''
    assert cv('fx_rate', 'abc') == ''

    assert cv('orig_amount', 12.5, 'SGD') == '12.50'
    assert cv('orig_amount', '12.5', 'sgd') == '12.50'
    assert cv('orig_amount', 200000, 'JPY') == '200000'
    assert cv('orig_amount', 200000.4, 'KRW') == '200000'
    assert cv('orig_amount', 12.345, 'USD') == '12.35'
    assert cv('orig_amount', '1,234.5', 'EUR') == '1234.50'
    assert cv('orig_amount', 12.5) == '12.50'                 # unknown/blank currency -> 2 dp
    assert cv('orig_amount', '', 'SGD') == '' and cv('orig_amount', None, 'SGD') == ''

    assert cv('currency', 'sgd') == 'SGD'
    assert cv('currency', ' Sgd ') == 'SGD'
    assert cv('currency', '') == '' and cv('currency', None) == '' and cv('currency', float('nan')) == ''
    # TWD (the value CURRENCY_OPTIONS/COUNTRY_CURRENCY carry) is TWD-native -> stored blank
    assert cv('currency', 'TWD') == '' and cv('currency', ' twd ') == ''

    # unchanged behaviour for the 9 legacy fields
    assert cv('amount', '1,200') == 1200 and isinstance(cv('amount', '1,200'), int)
    assert cv('amount', 12.5) == 12.5
    assert cv('date', '2026-09-08') == '09/08/2026'
    assert cv('notes', None) == ''


# ---------------------------------------------------------------------------
# add_expense
# ---------------------------------------------------------------------------

PAYLOAD_TWD = {'date': '2026-03-31', 'type_1': '📅 日常', 'category_type': '🧴 日用', 'amount': 240,
               'account': '菇菇', 'description': '印章', 'country': '台灣', 'location': '臺南', 'notes': ''}
PAYLOAD_SGD = {'date': '2026-09-06', 'type_1': '✈️ 旅行', 'category_type': '🍽️ 飲食', 'amount': 316,
               'account': '過兒', 'description': '咖啡', 'country': '新加坡', 'location': '新加坡',
               'notes': '', 'currency': 'SGD', 'orig_amount': 12.5, 'fx_rate': 25.2816}


def test_add_expense_9_column_sheet_unchanged(fake_st):
    ws = FakeWorksheet([EXPECTED_HEADERS])
    api = make_api(ws, fake_st)
    assert api.add_expense(dict(PAYLOAD_TWD)) is True
    assert ws.calls["append_row"] == [['03/31/2026', '📅 日常', '🧴 日用', 240, '菇菇', '印章', '台灣', '臺南', '']]
    assert api.last_write_warnings == []
    assert ws.calls["row_values"] == [1]


def test_add_expense_fx_payload_on_9_column_sheet_writes_twd_and_warns(fake_st):
    ws = FakeWorksheet([EXPECTED_HEADERS])
    api = make_api(ws, fake_st)
    assert api.add_expense(dict(PAYLOAD_SGD)) is True
    row = ws.calls["append_row"][0]
    assert len(row) == 9
    assert row == ['09/06/2026', '✈️ 旅行', '🍽️ 飲食', 316, '過兒', '咖啡', '新加坡', '新加坡', '']
    assert len(api.last_write_warnings) == 3
    assert any('幣別' in w and 'SGD' in w for w in api.last_write_warnings)
    assert any('原幣金額' in w for w in api.last_write_warnings)
    assert any('匯率' in w for w in api.last_write_warnings)
    assert ws.calls["row_values"] == [1]

    # a TWD payload with blank FX keys on the same sheet records nothing
    assert api.add_expense({**PAYLOAD_TWD, 'currency': '', 'orig_amount': '', 'fx_rate': ''}) is True
    assert api.last_write_warnings == []


def test_add_expense_fx_payload_on_12_column_sheet(fake_st):
    ws = FakeWorksheet([FX_HEADERS])
    api = make_api(ws, fake_st)
    assert api.add_expense(dict(PAYLOAD_SGD)) is True
    assert ws.calls["append_row"][0] == ['09/06/2026', '✈️ 旅行', '🍽️ 飲食', 316, '過兒', '咖啡',
                                         '新加坡', '新加坡', '', 'SGD', '12.50', '25.2816']
    assert api.last_write_warnings == []
    assert ws.calls["row_values"] == [1]

    # TWD row on the migrated sheet -> three blank FX cells
    assert api.add_expense(dict(PAYLOAD_TWD)) is True
    assert ws.calls["append_row"][1][9:] == ['', '', '']

    # JPY: 0 decimals for the original amount, rate still 6 dp
    jpy = {**PAYLOAD_SGD, 'amount': 41013, 'currency': 'jpy', 'orig_amount': 200000, 'fx_rate': 0.205065}
    assert api.add_expense(jpy) is True
    assert ws.calls["append_row"][2][9:] == ['JPY', '200000', '0.205065']


def test_add_expense_currency_twd_stores_blank_fx_cells(fake_st):
    """Regression: 'TWD' never lands in 幣別; K/L are forced blank with it (write-time invariant)."""
    ws = FakeWorksheet([FX_HEADERS])
    api = make_api(ws, fake_st)
    assert api.add_expense({**PAYLOAD_TWD, 'currency': 'TWD', 'orig_amount': '', 'fx_rate': ''}) is True
    assert ws.calls["append_row"][0][9:] == ['', '', '']
    # stale FX values alongside TWD are dropped, not stored
    assert api.add_expense({**PAYLOAD_TWD, 'currency': 'twd', 'orig_amount': 240, 'fx_rate': 1}) is True
    assert ws.calls["append_row"][1][9:] == ['', '', '']
    assert api.last_write_warnings == []
    df = api._load_from_api()
    assert list(df['currency']) == ['', ''] and df['orig_amount'].isna().all() and df['fx_rate'].isna().all()


def test_add_expense_shuffled_12_headers(fake_st):
    cols = list(FX_HEADERS)
    random.Random(3).shuffle(cols)
    ws = FakeWorksheet([cols])
    api = make_api(ws, fake_st)
    assert api.add_expense(dict(PAYLOAD_SGD)) is True
    row = ws.calls["append_row"][0]
    assert row[cols.index('幣別')] == 'SGD'
    assert row[cols.index('原幣金額')] == '12.50'
    assert row[cols.index('匯率')] == '25.2816'
    assert row[cols.index('金額')] == 316


def test_add_expense_refused_on_missing_required_header(fake_st):
    ws = FakeWorksheet([EXPECTED_HEADERS[:-1] + OPTIONAL_HEADERS])   # 備註 missing
    api = make_api(ws, fake_st)
    assert api.add_expense(dict(PAYLOAD_SGD)) is False
    assert ws.calls["append_row"] == []
    assert any('備註' in e for e in fake_st.errors)


# ---------------------------------------------------------------------------
# update_expense
# ---------------------------------------------------------------------------

def _original_sgd():
    return {'description': '咖啡', 'amount': 316.0, 'date': pd.Timestamp('2026-09-06')}


def test_update_expense_explicit_blank_fx_cells(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_TWD + ['', '', ''], ROW_SGD])
    api = make_api(ws, fake_st)
    ok = api.update_expense(3, _original_sgd(),
                            {'amount': 320, 'currency': '', 'orig_amount': '', 'fx_rate': ''})
    assert ok is True
    assert ws.rows[2] == ['09/06/2026', '✈️ 旅行', '🍽️ 飲食', '320', '過兒', '咖啡', '新加坡', '新加坡', '',
                          '', '', '']
    range_name, values = ws.calls["update"][0]
    assert range_name == 'A3:L3' and values[0][9:] == ['', '', '']
    assert ws.calls["row_values"].count(1) == 1


def test_update_expense_currency_blank_alone_blanks_orig_and_rate(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_SGD])
    api = make_api(ws, fake_st)
    assert api.update_expense(2, _original_sgd(), {'currency': ''}) is True
    assert ws.rows[1][9:] == ['', '', '']


def test_update_expense_currency_twd_normalises_to_blank_fx_cells(fake_st):
    """Regression: currency='TWD' must behave exactly like currency='' (plan §2.1/§2.4 invariant)."""
    jpy = {**PAYLOAD_SGD, 'amount': 41013, 'currency': 'JPY', 'orig_amount': 200000, 'fx_rate': 0.205065}
    ws = FakeWorksheet([FX_HEADERS])
    api = make_api(ws, fake_st)
    assert api.add_expense(jpy) is True
    orig = api._load_from_api().iloc[0].to_dict()
    assert orig['currency'] == 'JPY' and orig['orig_amount'] == 200000.0

    assert api.update_expense(2, orig, {'currency': 'TWD'}) is True
    assert ws.rows[1][9:] == ['', '', '']
    row = api._load_from_api().iloc[0]
    assert row['currency'] == '' and pd.isna(row['orig_amount']) and pd.isna(row['fx_rate'])

    # lower-case / padded TWD with stale FX values supplied alongside -> still all blank
    ws2 = FakeWorksheet([FX_HEADERS, ROW_SGD])
    api2 = make_api(ws2, fake_st)
    ok = api2.update_expense(2, _original_sgd(), {'currency': ' twd ', 'orig_amount': 12.5, 'fx_rate': 25.2816})
    assert ok is True
    assert ws2.rows[1][9:] == ['', '', '']


def test_update_expense_preserves_fx_cells_when_omitted(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_SGD])
    api = make_api(ws, fake_st)
    assert api.update_expense(2, _original_sgd(), {'description': '拿鐵', 'notes': 'x'}) is True
    assert ws.rows[1] == ['09/06/2026', '✈️ 旅行', '🍽️ 飲食', '316', '過兒', '拿鐵', '新加坡', '新加坡', 'x',
                          'SGD', '12.50', '25.2816']
    assert ws.calls["row_values"].count(1) == 1


def test_update_expense_rewrites_fx_with_currency_decimals(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_SGD])
    api = make_api(ws, fake_st)
    ok = api.update_expense(2, _original_sgd(), {'amount': 41013, 'currency': 'jpy',
                                                 'orig_amount': 200000, 'fx_rate': 0.205065})
    assert ok is True
    assert ws.rows[1][3] == '41013' and ws.rows[1][9:] == ['JPY', '200000', '0.205065']

    # orig_amount alone uses the currency already stored in the row (JPY -> 0 dp)
    orig = {'description': '咖啡', 'amount': 41013, 'date': '09/06/2026'}
    assert api.update_expense(2, orig, {'orig_amount': 210000.4}) is True
    assert ws.rows[1][9:] == ['JPY', '210000', '0.205065']


def test_update_expense_9_column_sheet_ignores_fx_keys_and_warns(fake_st):
    ws = FakeWorksheet([EXPECTED_HEADERS, ROW_TWD])
    api = make_api(ws, fake_st)
    orig = {'description': '印章', 'amount': 240.0, 'date': '03/31/2026'}
    ok = api.update_expense(2, orig, {'amount': 250, 'currency': 'SGD', 'orig_amount': 10, 'fx_rate': 25})
    assert ok is True
    assert ws.rows[1] == ['03/31/2026', '📅 日常', '🧴 日用', '250', '菇菇', '印章', '台灣', '臺南', '']
    assert ws.calls["update"][0][0] == 'A2:I2'
    assert len(api.last_write_warnings) == 3

    # a plain 9-field update on the 9-column sheet: byte-identical to today
    api.update_expense(2, {'description': '印章', 'amount': 250, 'date': '03/31/2026'}, {'notes': 'ok'})
    assert ws.rows[1][8] == 'ok' and api.last_write_warnings == []


def test_update_expense_grid_wider_than_header_untouched(fake_st):
    """26-column grid, 12 used headers: the write range stops at the last header column."""
    ws = FakeWorksheet([FX_HEADERS + [''] * 14, ROW_SGD + [''] * 14])
    api = make_api(ws, fake_st)
    assert api.update_expense(2, _original_sgd(), {'notes': 'n'}) is True
    assert ws.calls["update"][0][0] == 'A2:L2'
    assert len(ws.calls["update"][0][1][0]) == 12


# ---------------------------------------------------------------------------
# delete_expense (sanity: header read once, FX columns irrelevant)
# ---------------------------------------------------------------------------

def test_delete_expense_on_12_column_sheet(fake_st):
    ws = FakeWorksheet([FX_HEADERS, ROW_TWD + ['', '', ''], ROW_SGD])
    api = make_api(ws, fake_st)
    assert api.delete_expense(3, _original_sgd()) is True
    assert ws.calls["delete_rows"] == [3] and len(ws.rows) == 2
    assert ws.calls["row_values"].count(1) == 1
