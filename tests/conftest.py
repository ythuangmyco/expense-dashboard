"""
Shared pytest fixtures for the expense dashboard (PLAN_fx_and_overview.md §5 step 0).

Nothing here touches the real Google Sheet or any FX endpoint:
- ``FakeWorksheet`` / ``FakeSheetsAPI`` replace gspread with an in-memory grid.
- ``no_network`` (autouse) makes every ``requests`` call raise ``ConnectionError``
  unless the test carries ``@pytest.mark.allow_network`` or uses ``fake_requests``.
- ``df`` is the ``new_to_fill.csv`` snapshot with dates shifted so the newest row
  is ``helpers.today_local()``, processed through the real ``SheetsAPI._process_data``.

``auth.py`` is only monkeypatched (``patch_current_user``), never edited.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Streamlit "bare mode" (no ScriptRunContext) logs a warning per call; silence it.
for _name in ("streamlit", "streamlit.runtime.scriptrunner_utils.script_run_context",
              "streamlit.runtime.caching", "streamlit.runtime.state.session_state_proxy"):
    logging.getLogger(_name).setLevel(logging.ERROR)

import requests  # noqa: E402

from helpers import today_local  # noqa: E402

SNAPSHOT_CSV = ROOT / "new_to_fill.csv"
REQUIRED_HEADERS = ['日期', '類型_1', '類型_2', '金額', '帳戶', '名稱', '國家', '地點', '備註']
FX_HEADERS = ["幣別", "原幣金額", "匯率"]
SHEET_DATE_FORMAT = "%m/%d/%Y"
DEFAULT_GRID_WIDTH = 26          # the live tab is 26 columns wide
DEFAULT_GID = 453361449
DEFAULT_TITLE = "new_to_fill"


# ---------------------------------------------------------------------------
# A1 helpers
# ---------------------------------------------------------------------------

def col_letter(n: int) -> str:
    """1-based column number -> letters (1 -> A, 27 -> AA)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


_A1 = re.compile(r"^\$?([A-Za-z]+)\$?(\d+)$")


def parse_a1(range_name: str):
    """'J1' / 'J1:L1' / 'A2:Z2' -> (row1, col1, row2, col2), 1-based inclusive."""
    parts = range_name.split("!")[-1].split(":")
    m1 = _A1.match(parts[0])
    if not m1:
        raise ValueError(f"unsupported A1 range: {range_name}")
    r1, c1 = int(m1.group(2)), col_number(m1.group(1))
    if len(parts) == 1:
        return r1, c1, r1, c1
    m2 = _A1.match(parts[1])
    if not m2:
        raise ValueError(f"unsupported A1 range: {range_name}")
    return r1, c1, int(m2.group(2)), col_number(m2.group(1))


def _trim(row: Sequence[Any]) -> List[Any]:
    row = list(row)
    while row and (row[-1] is None or row[-1] == ""):
        row.pop()
    return row


# ---------------------------------------------------------------------------
# In-memory worksheet (subset of gspread.Worksheet used by the app)
# ---------------------------------------------------------------------------

class FakeWorksheet:
    """
    Minimal gspread.Worksheet stand-in backed by a rectangular list of lists.
    Mirrors the API's trimming: ``row_values``/``get`` drop trailing empty cells,
    ``get_all_values`` pads to the used width and drops trailing empty rows.
    Every write is recorded in ``self.calls`` as (method, args, kwargs).
    """

    def __init__(self, rows: Optional[Iterable[Sequence[Any]]] = None, *,
                 width: int = DEFAULT_GRID_WIDTH, title: str = DEFAULT_TITLE,
                 gid: int = DEFAULT_GID):
        self.title = title
        self.id = gid
        self._width = width
        self._rows: List[List[Any]] = []
        for r in (rows or []):
            self._rows.append(self._pad(list(r)))
        if not self._rows:
            self._rows.append(self._pad([]))
        self.calls: List[tuple] = []

    # -- geometry ------------------------------------------------------
    def _pad(self, row: List[Any]) -> List[Any]:
        if len(row) > self._width:
            self._width = len(row)
            self._rows = [r + [""] * (self._width - len(r)) for r in self._rows]
        return [("" if v is None else v) for v in row] + [""] * (self._width - len(row))

    def _ensure_rows(self, n: int):
        while len(self._rows) < n:
            self._rows.append(self._pad([]))

    @property
    def col_count(self) -> int:
        return self._width

    @property
    def row_count(self) -> int:
        return len(self._rows)

    def add_cols(self, cols: int):
        self.calls.append(("add_cols", (cols,), {}))
        self._width += cols
        self._rows = [r + [""] * cols for r in self._rows]

    def add_rows(self, rows: int):
        self.calls.append(("add_rows", (rows,), {}))
        self._ensure_rows(len(self._rows) + rows)

    # -- reads ---------------------------------------------------------
    def used_rows(self) -> List[List[Any]]:
        rows = list(self._rows)
        while rows and not _trim(rows[-1]):
            rows.pop()
        return rows

    def row_values(self, row: int, **kwargs) -> List[Any]:
        if row < 1 or row > len(self._rows):
            return []
        return _trim(self._rows[row - 1])

    def get_all_values(self, **kwargs) -> List[List[Any]]:
        rows = self.used_rows()
        width = max((len(_trim(r)) for r in rows), default=0)
        return [list(r[:width]) for r in rows]

    def get(self, range_name: Optional[str] = None, **kwargs) -> List[List[Any]]:
        if range_name is None:
            return self.get_all_values()
        r1, c1, r2, c2 = parse_a1(range_name)
        out = []
        for r in range(r1, r2 + 1):
            row = self._rows[r - 1] if r <= len(self._rows) else []
            out.append(_trim(row[c1 - 1:c2]))
        while out and not out[-1]:
            out.pop()
        return out

    def acell(self, label: str, **kwargs):
        r, c, _, _ = parse_a1(label)
        value = self._rows[r - 1][c - 1] if r <= len(self._rows) and c <= self._width else ""

        class _Cell:
            pass
        cell = _Cell()
        cell.value = value
        cell.row, cell.col = r, c
        return cell

    # -- writes --------------------------------------------------------
    def append_row(self, values: Sequence[Any], value_input_option: Any = "RAW", **kwargs):
        self.calls.append(("append_row", (list(values),), {"value_input_option": value_input_option, **kwargs}))
        used = self.used_rows()
        insert_at = len(used)             # 0-based index of the new row
        new_row = self._pad(list(values))
        if insert_at < len(self._rows):
            self._rows[insert_at] = new_row
        else:
            self._rows.append(new_row)
        return {"updates": {"updatedRange": f"{self.title}!A{insert_at + 1}:{col_letter(len(values))}{insert_at + 1}"}}

    def append_rows(self, values: Sequence[Sequence[Any]], **kwargs):
        for row in values:
            self.append_row(row, **kwargs)

    def update(self, *args, values: Any = None, range_name: Optional[str] = None, **kwargs):
        # gspread 6: update(range_name, values) (positional, deprecated) or keywords
        for a in args:
            if isinstance(a, str):
                range_name = a
            else:
                values = a
        if range_name is None or values is None:
            raise TypeError("update() needs range_name and values")
        self.calls.append(("update", (), {"range_name": range_name, "values": values, **kwargs}))
        r1, c1, r2, c2 = parse_a1(range_name)
        self._ensure_rows(r2)
        if c2 > self._width:
            raise ValueError(f"range {range_name} exceeds grid limits (max {self._width} cols)")
        for i, row in enumerate(values):
            r = r1 + i
            if r > r2:
                break
            self._ensure_rows(r)
            for j, v in enumerate(row):
                c = c1 + j
                if c > c2:
                    break
                self._rows[r - 1][c - 1] = "" if v is None else v
        return {"updatedRange": range_name}

    def update_acell(self, label: str, value: Any):
        return self.update(values=[[value]], range_name=label)

    def delete_rows(self, start_index: int, end_index: Optional[int] = None):
        self.calls.append(("delete_rows", (start_index, end_index), {}))
        end = end_index or start_index
        if start_index < 1 or end > len(self._rows):
            raise ValueError(f"delete_rows({start_index}, {end_index}) out of range")
        del self._rows[start_index - 1:end]
        if not self._rows:
            self._rows.append(self._pad([]))
        return {}

    # -- convenience for assertions -----------------------------------
    def header(self) -> List[Any]:
        return self.row_values(1)

    def data_rows(self) -> List[List[Any]]:
        return [list(r) for r in self.used_rows()[1:]]


def make_fake_ws(header: Optional[Sequence[str]] = None,
                 rows: Optional[Iterable[Sequence[Any]]] = None, *,
                 width: int = DEFAULT_GRID_WIDTH, **kw) -> FakeWorksheet:
    """Worksheet with ``header`` (default: the 9 required names) followed by ``rows``."""
    header = list(REQUIRED_HEADERS if header is None else header)
    return FakeWorksheet([header, *(rows or [])], width=width, **kw)


# ---------------------------------------------------------------------------
# Stub SheetsAPI bound to a FakeWorksheet (real read/write code paths)
# ---------------------------------------------------------------------------

def make_fake_api(worksheet: FakeWorksheet):
    import sheets_api as sa

    class FakeSheetsAPI(sa.SheetsAPI):
        """SheetsAPI whose connection step is replaced by the in-memory worksheet."""

        def __init__(self, ws):
            self._fake_ws = ws
            super().__init__()

        def _initialize_api(self):
            self.client = None
            self.worksheet = self._fake_ws
            self.api_available = True
            self.read_only = False
            self.init_error = None

    return FakeSheetsAPI(worksheet)


# ---------------------------------------------------------------------------
# Snapshot CSV -> shifted rows -> df
# ---------------------------------------------------------------------------

def _load_snapshot_rows() -> List[List[str]]:
    with SNAPSHOT_CSV.open(encoding="utf-8", newline="") as fh:
        rows = [list(r) for r in csv.reader(fh)]
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    date_idx = header.index("日期")
    parsed = []
    for r in body:
        try:
            parsed.append(datetime.strptime(r[date_idx].strip(), SHEET_DATE_FORMAT).date())
        except ValueError:
            parsed.append(None)
    newest = max(d for d in parsed if d is not None)
    shift = today_local() - newest
    for r, d in zip(body, parsed):
        if d is not None:
            r[date_idx] = (d + shift).strftime(SHEET_DATE_FORMAT)
    return [header, *body]


@pytest.fixture(scope="session")
def snapshot_rows() -> List[List[str]]:
    """Raw string rows of new_to_fill.csv (header first), dates shifted so max == today."""
    return _load_snapshot_rows()


@pytest.fixture
def today():
    return today_local()


@pytest.fixture
def fake_ws() -> FakeWorksheet:
    """Empty worksheet with the 9 required headers (un-migrated), 26 columns wide."""
    return make_fake_ws()


@pytest.fixture
def fake_ws_migrated() -> FakeWorksheet:
    """Empty worksheet already carrying 幣別/原幣金額/匯率 in J1:L1."""
    return make_fake_ws(REQUIRED_HEADERS + FX_HEADERS)


@pytest.fixture
def snapshot_ws(snapshot_rows) -> FakeWorksheet:
    """Worksheet populated with the shifted snapshot (fresh copy per test)."""
    return FakeWorksheet([list(r) for r in snapshot_rows])


@pytest.fixture
def fake_api(fake_ws):
    """Stub SheetsAPI over ``fake_ws``; use ``use_fake_api`` to wire it into the modules."""
    return make_fake_api(fake_ws)


@pytest.fixture
def snapshot_api(snapshot_ws):
    return make_fake_api(snapshot_ws)


@pytest.fixture
def df(snapshot_api):
    """Processed DataFrame of the shifted snapshot via the real loader."""
    return snapshot_api._load_from_api()


# ---------------------------------------------------------------------------
# Monkeypatch helpers
# ---------------------------------------------------------------------------

def _patch_sheets_api(monkeypatch, api):
    import sheets_api as sa
    monkeypatch.setattr(sa, "_sheets_api", api)
    monkeypatch.setattr(sa, "get_sheets_api", lambda: api)
    import input_forms
    monkeypatch.setattr(input_forms, "get_sheets_api", lambda: api)
    app = sys.modules.get("app")          # app.py runs set_page_config on import; patch only if loaded
    if app is not None and hasattr(app, "get_sheets_api"):
        monkeypatch.setattr(app, "get_sheets_api", lambda: api)
    return api


@pytest.fixture
def use_fake_api(monkeypatch, fake_api):
    """Wire ``fake_api`` into sheets_api.get_sheets_api / input_forms.get_sheets_api."""
    return _patch_sheets_api(monkeypatch, fake_api)


@pytest.fixture
def patch_sheets_api(monkeypatch) -> Callable[[Any], Any]:
    """Factory: ``patch_sheets_api(api)`` wires any stub API into the modules."""
    return lambda api: _patch_sheets_api(monkeypatch, api)


@pytest.fixture
def patch_current_user(monkeypatch) -> Callable[[str], str]:
    """
    Factory: ``patch_current_user("菇菇")`` makes ``input_forms.get_current_user``
    and ``auth.get_current_user`` return that name (auth.py itself is never edited).
    """
    def _set(name: str = "菇菇") -> str:
        import auth
        monkeypatch.setattr(auth, "get_current_user", lambda: name)
        import input_forms
        monkeypatch.setattr(input_forms, "get_current_user", lambda: name)
        app = sys.modules.get("app")
        if app is not None and hasattr(app, "get_current_user"):
            monkeypatch.setattr(app, "get_current_user", lambda: name)
        return name
    return _set


@pytest.fixture
def patch_load_expense_data(monkeypatch) -> Callable[[Any], Any]:
    """Factory: ``patch_load_expense_data(df)`` makes every module's load_expense_data return df."""
    def _set(frame):
        import sheets_api as sa
        monkeypatch.setattr(sa, "load_expense_data", lambda: frame)
        monkeypatch.setattr(sa, "_load_expense_data_cached", lambda: frame)
        for mod_name in ("app", "input_forms"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "load_expense_data"):
                monkeypatch.setattr(mod, "load_expense_data", lambda: frame)
        return frame
    return _set


# ---------------------------------------------------------------------------
# Network guard
# ---------------------------------------------------------------------------

class NetworkBlocked(requests.ConnectionError):
    pass


class NetworkGuard:
    """Records every blocked call as (target, kwargs) in ``calls``."""

    def __init__(self):
        self.calls: List[tuple] = []

    def __call__(self, *args, **kwargs):
        target = args[0] if args else kwargs.get("url", "?")
        self.calls.append((target, kwargs))
        raise NetworkBlocked(f"network access blocked in tests: {target}")


_blocked = NetworkGuard()


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """
    Autouse: every ``requests`` call raises ``requests.ConnectionError``.
    Opt out with ``@pytest.mark.allow_network`` (real network) or use ``fake_requests``.
    Yields the guard; ``no_network.calls`` lists every blocked attempt.
    """
    if request.node.get_closest_marker("allow_network"):
        yield None
        return
    _blocked.calls.clear()
    monkeypatch.setattr(requests, "get", _blocked)
    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr(requests, "request", _blocked)
    monkeypatch.setattr(requests.Session, "request", lambda self, *a, **k: _blocked(*a[1:], **k))
    yield _blocked


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: Optional[str] = None,
                 headers: Optional[Dict[str, str]] = None, url: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.text = text if text is not None else ("" if json_data is None else __import__("json").dumps(json_data))
        self.content = self.text.encode("utf-8")
        self.headers = headers or {"content-type": "application/json"}
        self.url = url
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code} for {self.url}", response=self)


class FakeRequests:
    """
    Router installed over ``requests.get``: ``add(substring, json=..., status=...)``
    or ``add(substring, exc=requests.Timeout())``. Unmatched URLs raise ConnectionError.
    ``calls`` records every (url, kwargs).
    """

    def __init__(self):
        self.routes: List[tuple] = []
        self.calls: List[tuple] = []

    def add(self, url_part: str, *, json: Any = None, status: int = 200, text: Optional[str] = None,
            exc: Optional[BaseException] = None, headers: Optional[Dict[str, str]] = None):
        self.routes.append((url_part, json, status, text, exc, headers))
        return self

    def get(self, url: str, *args, **kwargs):
        self.calls.append((url, kwargs))
        for part, json_data, status, text, exc, headers in self.routes:
            if part in url:
                if exc is not None:
                    raise exc
                return FakeResponse(status, json_data, text, headers, url)
        raise NetworkBlocked(f"no fake route for {url}")


@pytest.fixture
def fake_requests(no_network, monkeypatch) -> FakeRequests:
    """Route ``requests.get`` to canned responses (installed after ``no_network``)."""
    router = FakeRequests()
    monkeypatch.setattr(requests, "get", router.get)
    return router


def pytest_configure(config):
    config.addinivalue_line("markers", "allow_network: let the test reach the real network")


# ---------------------------------------------------------------------------
# AppTest harness for app.main()
# ---------------------------------------------------------------------------

def _import_app():
    """Import app.py outside a ScriptRunContext (set_page_config/markdown become no-ops)."""
    import app  # noqa: F401
    return sys.modules["app"]


def _run_app_main():
    # Re-executed by AppTest from its source: must be self-contained.
    import app
    app.main()


@pytest.fixture
def app_test(monkeypatch, snapshot_api, patch_sheets_api, patch_current_user):
    """
    Factory: ``app_test(api=None, user="菇菇", authed=True)`` -> ``AppTest`` bound to
    ``app.main`` with the stub API wired in and the session pre-authenticated.
    """
    from streamlit.testing.v1 import AppTest
    import sheets_api as sa

    app = _import_app()

    def _blocked_init(self):
        raise AssertionError("SheetsAPI._initialize_api reached in an AppTest run (stub not wired)")
    monkeypatch.setattr(sa.SheetsAPI, "_initialize_api", _blocked_init)

    def _make(api=None, user: str = "菇菇", authed: bool = True, timeout: float = 30):
        api = api or snapshot_api
        patch_sheets_api(api)
        patch_current_user(user)
        # cache_data is process-wide: drop any df cached by an earlier test/run.
        try:
            sa._load_expense_data_cached.clear()
        except Exception:
            pass
        at = AppTest.from_function(_run_app_main, default_timeout=timeout)
        at.session_state["password_correct"] = authed
        at.session_state["current_user"] = user if authed else None
        return at
    return _make
