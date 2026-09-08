"""
scripts/migrate_add_currency_columns.py on a fake worksheet (plan §5 step 2b).
"""

import io
import random
import sys
from pathlib import Path

import pytest

from conftest import FX_HEADERS, REQUIRED_HEADERS, make_fake_ws

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import migrate_add_currency_columns as mig  # noqa: E402

DATA = [
    ["09/01/2026", "📅 日常", "🍽️ 飲食", "120", "菇菇", "午餐", "台灣", "臺南", ""],
    ["09/02/2026", "✈️ 旅行", "🚗 交通", "18,900", "過兒", "機票", "新加坡", "新加坡", "備註"],
]


def _run(ws, **kw):
    out = io.StringIO()
    code = mig.run(ws, out=out, **kw)
    return code, out.getvalue()


def test_nine_headers_in_order_writes_J1_L1():
    ws = make_fake_ws(REQUIRED_HEADERS, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert ws.header() == REQUIRED_HEADERS + FX_HEADERS
    assert "J1:L1" in out and "J, K, L" in out
    assert "resulting header row" in out
    # exactly one RAW write, addressed by cell range, header row only
    writes = [c for c in ws.calls if c[0] == "update"]
    assert len(writes) == 1
    assert writes[0][2]["range_name"] == "J1:L1"
    assert writes[0][2]["value_input_option"] == "RAW"
    assert writes[0][2]["values"] == [FX_HEADERS]


def test_any_order_headers_write_into_first_empty_cells():
    shuffled = list(REQUIRED_HEADERS)
    random.Random(7).shuffle(shuffled)
    assert shuffled != REQUIRED_HEADERS
    ws = make_fake_ws(shuffled, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert ws.header() == shuffled + FX_HEADERS
    assert "J1:L1" in out


def test_extra_used_header_shifts_targets_after_last_non_empty():
    header = REQUIRED_HEADERS + ["合併地點"]          # 10 used columns -> K..M
    ws = make_fake_ws(header, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert ws.header() == header + FX_HEADERS
    assert "K1:M1" in out and "K, L, M" in out


def test_gap_in_header_targets_after_last_non_empty():
    header = REQUIRED_HEADERS + ["", "備用"]          # J empty, K used -> targets L..N
    ws = make_fake_ws(header, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert ws.row_values(1) == header + FX_HEADERS
    assert "L1:N1" in out


def test_data_rows_never_touched():
    ws = make_fake_ws(REQUIRED_HEADERS, DATA)
    before = ws.data_rows()
    _run(ws)
    assert ws.data_rows() == before
    assert all(c[0] in ("update", "add_cols") for c in ws.calls)
    assert not any(c[0] in ("append_row", "delete_rows") for c in ws.calls)


def test_already_migrated_is_noop():
    ws = make_fake_ws(REQUIRED_HEADERS + FX_HEADERS, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert "already migrated" in out
    assert ws.calls == []


def test_already_migrated_any_position_is_noop():
    header = ["匯率"] + REQUIRED_HEADERS + ["幣別", "原幣金額"]
    ws = make_fake_ws(header, DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_OK and "already migrated" in out
    assert ws.calls == []


def test_partial_fx_headers_refused():
    ws = make_fake_ws(REQUIRED_HEADERS + ["幣別"], DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_REFUSED
    assert "REFUSED" in out
    assert ws.calls == []


def test_non_empty_target_refused():
    # J1 holds whitespace: not a header name, but not an empty cell either
    ws = make_fake_ws(REQUIRED_HEADERS + ["   "], DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_REFUSED
    assert "not empty" in out and "J" in out
    assert ws.calls == []
    assert ws.row_values(1) == REQUIRED_HEADERS + ["   "]


def test_missing_required_name_refused():
    header = [h for h in REQUIRED_HEADERS if h != "備註"]
    ws = make_fake_ws(header, [r[:-1] for r in DATA])
    code, out = _run(ws)
    assert code == mig.EXIT_REFUSED
    assert "備註" in out
    assert ws.calls == []
    assert ws.header() == header


def test_duplicate_header_names_refused():
    ws = make_fake_ws(REQUIRED_HEADERS + ["金額"], DATA)
    code, out = _run(ws)
    assert code == mig.EXIT_REFUSED
    assert ws.calls == []


def test_dry_run_writes_nothing_and_prints_letters():
    ws = make_fake_ws(REQUIRED_HEADERS, DATA)
    code, out = _run(ws, dry_run=True)
    assert code == mig.EXIT_OK
    assert "J1:L1" in out and "dry run" in out
    assert "would be" in out and "幣別" in out
    assert ws.calls == []
    assert ws.header() == REQUIRED_HEADERS


def test_narrow_grid_is_widened_before_write():
    ws = make_fake_ws(REQUIRED_HEADERS, DATA, width=9)
    code, out = _run(ws)
    assert code == mig.EXIT_OK
    assert ws.col_count == 12
    assert ws.header() == REQUIRED_HEADERS + FX_HEADERS
    assert ws.data_rows()[0][:9] == DATA[0]


def test_plan_migration_pure():
    plan = mig.plan_migration(REQUIRED_HEADERS + ["", "", None])
    assert plan.target_letters == ["J", "K", "L"]
    assert plan.resulting_header == REQUIRED_HEADERS + FX_HEADERS
    with pytest.raises(mig.MigrationRefused):
        mig.plan_migration(REQUIRED_HEADERS[:-1])


def test_resolve_settings_precedence(tmp_path):
    parser = mig.build_parser()
    secrets = {"app": {"sheet_id": "SECRET_ID", "worksheet_gid": 1290819173},
               "google_sheets": {"type": "service_account"}}
    s = mig.resolve_settings(parser.parse_args([]), secrets)
    assert s["sheet_id"] == "SECRET_ID" and s["worksheet_gid"] == 1290819173
    assert s["service_account_info"] == {"type": "service_account"}

    s = mig.resolve_settings(parser.parse_args(["--sheet-id", "CLI", "--worksheet-gid", "5",
                                                 "--service-account", "k.json"]), secrets)
    assert s["sheet_id"] == "CLI" and s["worksheet_gid"] == 5 and s["service_account_file"] == "k.json"

    s = mig.resolve_settings(parser.parse_args([]), {})
    assert s["sheet_id"] == mig.SHEET_ID and s["worksheet_gid"] == mig.WORKSHEET_GID
    assert s["service_account_info"] is None

    # read_secrets tolerates a missing file
    assert mig.read_secrets(tmp_path / "nope.toml") == {}


def test_main_dry_run_uses_injected_worksheet(monkeypatch, capsys):
    ws = make_fake_ws(REQUIRED_HEADERS, DATA)
    monkeypatch.setattr(mig, "read_secrets", lambda *a, **k: {})
    monkeypatch.setattr(mig, "open_worksheet", lambda settings: ws)
    code = mig.main(["--dry-run", "--worksheet-gid", "1290819173", "--service-account", "x.json"])
    out = capsys.readouterr().out
    assert code == mig.EXIT_OK
    assert "gid 1290819173" in out and "J1:L1" in out
    assert ws.calls == []


def test_main_without_credentials_is_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(mig, "read_secrets", lambda *a, **k: {})
    code = mig.main([])
    assert code == mig.EXIT_USAGE
    assert "credentials" in capsys.readouterr().out
