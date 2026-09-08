#!/usr/bin/env python
"""
Add the three optional foreign-currency headers (幣別 / 原幣金額 / 匯率) to the
expense worksheet's header row. PLAN_fx_and_overview.md §2.4.

What it does
- reads row 1; refuses unless all 9 required names are present (any order);
- if the 3 FX names are already present: prints "already migrated", exit 0;
- otherwise writes the 3 names, RAW, by cell address into the first three
  consecutive empty header cells after the last non-empty header (J1:L1 on a
  9-column sheet), refusing if any target cell is non-empty;
- prints the target letters and the resulting header row. Data rows are never touched.

Usage
    python scripts/migrate_add_currency_columns.py --dry-run
    python scripts/migrate_add_currency_columns.py
    python scripts/migrate_add_currency_columns.py --sheet-id ID --worksheet-gid GID \
        --service-account path/to/key.json

Defaults come from .streamlit/secrets.toml ([app] sheet_id / worksheet_gid,
[google_sheets] credentials) when present, else config.py.

Exit codes: 0 done / already migrated, 1 refused, 2 usage or connection error.
Rollback: clear the three header cells (find them by name); the app tolerates their absence.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import OPTIONAL_HEADERS, SHEET_ID, WORKSHEET_GID  # noqa: E402

SECRETS_PATH = ROOT / ".streamlit" / "secrets.toml"
# Mirrors sheets_api.EXPECTED_HEADERS (kept local so the script does not import Streamlit).
REQUIRED_HEADERS = ['日期', '類型_1', '類型_2', '金額', '帳戶', '名稱', '國家', '地點', '備註']
FX_HEADERS = list(OPTIONAL_HEADERS)

EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2


class MigrationRefused(Exception):
    """The header row is not in a state this script is willing to change."""


@dataclass
class Plan:
    already_migrated: bool
    header: List[str]                       # stripped row-1 values as read
    target_cols: List[int] = field(default_factory=list)   # 1-based column numbers
    resulting_header: List[str] = field(default_factory=list)

    @property
    def target_letters(self) -> List[str]:
        return [col_letter(c) for c in self.target_cols]

    @property
    def target_range(self) -> str:
        return f"{self.target_letters[0]}1:{self.target_letters[-1]}1"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested on a fake worksheet)
# ---------------------------------------------------------------------------

def col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _is_empty(value: Any) -> bool:
    return value is None or str(value) == ""


def plan_migration(raw_header: Sequence[Any]) -> Plan:
    """
    Decide what to do from the raw row-1 values (as returned by ``row_values(1)``).
    Raises MigrationRefused when a required name is missing or the FX names are only
    partially present.
    """
    header = [("" if v is None else str(v).strip()) for v in raw_header]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        raise MigrationRefused(f"標題列缺少必要欄位 {missing}；目前標題列: {header}")

    present = [h for h in FX_HEADERS if h in header]
    if len(present) == len(FX_HEADERS):
        return Plan(already_migrated=True, header=header)
    if present:
        raise MigrationRefused(f"標題列只包含部分外幣欄位 {present}，請手動處理後再執行")

    duplicates = sorted({h for h in header if h and header.count(h) > 1})
    if duplicates:
        raise MigrationRefused(f"標題列有重複欄位名稱 {duplicates}")

    last_used = max((i for i, h in enumerate(header) if h), default=-1)   # 0-based
    first_target = last_used + 2                                          # 1-based column
    targets = list(range(first_target, first_target + len(FX_HEADERS)))

    resulting = list(header[:last_used + 1]) + FX_HEADERS
    return Plan(already_migrated=False, header=header, target_cols=targets, resulting_header=resulting)


def _read_target_cells(ws, plan: Plan) -> List[Any]:
    """Raw content of the target cells (whitespace-only cells count as non-empty)."""
    rows = ws.get(plan.target_range) or [[]]
    cells = list(rows[0]) if rows else []
    return cells + [""] * (len(plan.target_cols) - len(cells))


def run(ws, *, dry_run: bool = False, out=None) -> int:
    """
    Apply the migration to worksheet ``ws`` (gspread Worksheet or a compatible fake).
    Returns an exit code; every message goes to ``out`` (default stdout).
    """
    out = out or sys.stdout
    header_raw = ws.row_values(1)
    try:
        plan = plan_migration(header_raw)
    except MigrationRefused as e:
        print(f"REFUSED: {e}", file=out)
        return EXIT_REFUSED

    if plan.already_migrated:
        print(f"already migrated: {FX_HEADERS} present in row 1", file=out)
        print(f"header row: {plan.header}", file=out)
        return EXIT_OK

    # Guard against whitespace cells / concurrent edits: re-read the exact target cells.
    current = _read_target_cells(ws, plan)
    occupied = [(letter, val) for letter, val in zip(plan.target_letters, current) if not _is_empty(val)]
    if occupied:
        print(f"REFUSED: target cells are not empty: {occupied}", file=out)
        return EXIT_REFUSED

    print(f"target cells: {plan.target_range} ({', '.join(plan.target_letters)}) "
          f"<- {FX_HEADERS}", file=out)

    if dry_run:
        print("dry run: nothing written", file=out)
        print(f"resulting header row would be: {plan.resulting_header}", file=out)
        return EXIT_OK

    needed = plan.target_cols[-1]
    col_count = getattr(ws, "col_count", None)
    if col_count is not None and needed > col_count:
        extra = needed - col_count
        print(f"grid is {col_count} columns wide; adding {extra} column(s)", file=out)
        ws.add_cols(extra)

    ws.update(values=[list(FX_HEADERS)], range_name=plan.target_range, value_input_option="RAW")

    after = [("" if v is None else str(v).strip()) for v in ws.row_values(1)]
    still_missing = [h for h in FX_HEADERS if h not in after]
    if still_missing:
        print(f"ERROR: wrote {plan.target_range} but {still_missing} not found on re-read: {after}", file=out)
        return EXIT_REFUSED
    print(f"written {plan.target_range}", file=out)
    print(f"resulting header row: {after}", file=out)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Settings / connection
# ---------------------------------------------------------------------------

def read_secrets(path: Path = SECRETS_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {}
    import tomllib
    with path.open("rb") as fh:
        return tomllib.load(fh)


def resolve_settings(args: argparse.Namespace, secrets: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """CLI flag > secrets.toml ([app] / [google_sheets]) > config.py."""
    secrets = read_secrets() if secrets is None else secrets
    app = secrets.get("app", {}) if isinstance(secrets.get("app"), dict) else {}
    sheet_id = args.sheet_id or app.get("sheet_id") or SHEET_ID
    gid = args.worksheet_gid if args.worksheet_gid is not None else app.get("worksheet_gid", WORKSHEET_GID)
    creds_info = secrets.get("google_sheets") if isinstance(secrets.get("google_sheets"), dict) else None
    return {
        "sheet_id": str(sheet_id),
        "worksheet_gid": int(gid),
        "service_account_file": args.service_account,
        "service_account_info": creds_info,
    }


def open_worksheet(settings: Dict[str, Any]):
    import gspread

    if settings.get("service_account_file"):
        client = gspread.service_account(filename=settings["service_account_file"])
    elif settings.get("service_account_info"):
        client = gspread.service_account_from_dict(dict(settings["service_account_info"]))
    else:
        raise SystemExit("no credentials: pass --service-account or fill [google_sheets] in .streamlit/secrets.toml")
    spreadsheet = client.open_by_key(settings["sheet_id"])
    return spreadsheet.get_worksheet_by_id(settings["worksheet_gid"])


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sheet-id", default=None, help="spreadsheet id (default: secrets [app] sheet_id, else config)")
    p.add_argument("--worksheet-gid", type=int, default=None,
                   help="worksheet gid (default: secrets [app] worksheet_gid, else config.WORKSHEET_GID)")
    p.add_argument("--service-account", default=None,
                   help="service-account JSON file (default: secrets [google_sheets])")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    settings = resolve_settings(args)
    print(f"spreadsheet {settings['sheet_id']} / worksheet gid {settings['worksheet_gid']}"
          f"{' (dry run)' if args.dry_run else ''}")
    try:
        ws = open_worksheet(settings)
    except SystemExit as e:
        print(f"ERROR: {e}")
        return EXIT_USAGE
    except Exception as e:  # gspread / auth errors
        print(f"ERROR: cannot open worksheet: {e}")
        return EXIT_USAGE
    print(f"worksheet: {getattr(ws, 'title', '?')} (gid {getattr(ws, 'id', '?')})")
    return run(ws, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
