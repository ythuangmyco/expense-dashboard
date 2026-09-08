"""
Streamlit entry wrapper for the headless-Chrome harness (PLAN §5, step 5 tooling).

Runs the REAL app.py with every external dependency stubbed so a browser can
drive it end-to-end with NO network access to Google Sheets or any FX endpoint:

* gspread  -> in-memory worksheet seeded from ``new_to_fill.csv`` (first 40 rows
              + adversarial rows + one already-converted SGD row). Every write
              (append_row / update / delete_rows) is appended as one JSON line to
              ``tests/chrome/out/writes_<MODE>.jsonl`` so a driver can assert on it.
* requests -> ``requests.get`` is monkeypatched: FX endpoints are answered from
              local fixtures / the tables below, the Google CSV export URL from the
              snapshot file, and ANY other URL raises ``ConnectionError``.

Environment:
    MODE=api|csv     api  = fake gspread client, writable (default)
                     csv  = gspread init fails as in production with placeholder
                            secrets; the app falls back to the CSV export (read-only)
    FX_HEADERS=1|0   1 = header row J..L carries 幣別 原幣金額 匯率 (migrated, default)
                     0 = 9-column legacy sheet (un-migrated)
    FX_MODE=live|fail|slow
                     live = every FX source answers (Frankfurter first, so the app
                            reports ✅ Frankfurter with the rate in HARNESS_RATES)
                     fail = every FX call raises ConnectionError immediately
                     slow = every FX call sleeps FX_TIMEOUT_S then raises Timeout
    HARNESS_OUT      directory for the write log (default tests/chrome/out)

Start it with:
    expense_env/bin/streamlit run tests/chrome/runner.py --server.port 8780 \
        --server.headless true --browser.gatherUsageStats false
"""
import csv
import io
import json
import os
import re
import runpy
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

MODE = os.environ.get("MODE", "api")
FX_HEADERS = os.environ.get("FX_HEADERS", "1") != "0"
FX_MODE = os.environ.get("FX_MODE", "live")
OUT_DIR = os.environ.get("HARNESS_OUT") or os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)
WRITE_LOG = os.path.join(OUT_DIR, f"writes_{MODE}.jsonl")

import requests  # noqa: E402
import gspread  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

from config import FX_ENDPOINTS, FX_TIMEOUT_S  # noqa: E402

if HERE not in sys.path:
    sys.path.insert(0, HERE)
from fxfixtures import CONVERTED_ROW, HARNESS_DATE, HARNESS_RATES  # noqa: E402

CSV_PATH = os.path.join(REPO, "new_to_fill.csv")
with open(CSV_PATH, "rb") as f:
    CSV_BYTES = f.read()

REQUIRED_HEADERS = ["日期", "類型_1", "類型_2", "金額", "帳戶", "名稱", "國家", "地點", "備註"]
FX_HEADER_NAMES = ["幣別", "原幣金額", "匯率"]


def _seed_rows():
    text = CSV_BYTES.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    header, data = rows[0], rows[1:41]
    header = [h.strip() for h in header]
    # adversarial rows (kept from the review harness)
    data += [
        ["06/17/2026", "✈️ 旅行", "🚗 交通", "26,495.00", "過兒", "加拿大機票", "加拿大", "溫哥華", "過兒機票"],  # exact dup
        ["09/02/2026", "📅 日常", "👶 寶寶", "26,495.00", "菇菇", "嬰兒車", "台灣", "臺南", ""],
        ["09/02/2026", "📅 日常", "👶 寶寶", "26,495.00", "菇菇", "嬰兒車", "台灣", "臺南", ""],  # dup 嬰兒車
        ["09/03/2026", "📅 日常", "🍽️ 飲食", "abc", "菇菇", "壞金額", "台灣", "臺南", ""],
        ["09/03/2026", "📅 日常", "🍽️ 飲食", "-500", "過兒", "退款", "台灣", "臺南", "refund"],
        ["", "", "", "", "", "", "", "", ""],  # empty row
        ["2026-09-04", "📅 日常", "🍽️ 飲食", "NT$1,200", "菇菇", "ISO日期", "台灣", "臺南", ""],
        ["31/12/2026", "📅 日常", "🍽️ 飲食", "300", "菇菇", "壞日期", "台灣", "臺南", ""],
        ["09/05/2026", "🎁 其他類型", "🎁 禮物", "999", "阿嬤", "未知帳戶", "冰島", "雷克雅維克", ""],
        ["09/06/2026", "📅 日常", "🍽️ 飲食", "150", "菇菇", "今日午餐", "台灣", "臺南", ""],
    ]
    if FX_HEADERS:
        header = header + FX_HEADER_NAMES
        data.append(list(CONVERTED_ROW))
    return [header] + data


class FakeWorksheet:
    id = 453361449
    title = "Plain"

    def __init__(self):
        self.rows = _seed_rows()

    def _log(self, op, **kw):
        with open(WRITE_LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "op": op, **kw}, ensure_ascii=False, default=str) + "\n")

    def get_all_values(self):
        return [list(r) for r in self.rows]

    def row_values(self, n):
        n = int(n)
        assert type(n) is int
        if n < 1 or n > len(self.rows):
            return []
        return list(self.rows[n - 1])

    def append_row(self, values, **kw):
        self._log("append_row", values=values, types=[type(v).__name__ for v in values], kw=kw)
        self.rows.append([str(v) if v is not None else "" for v in values])

    def update(self, values=None, range_name=None, **kw):
        self._log("update", values=values, range_name=range_name, kw=kw)
        m = re.match(r"A(\d+):[A-Z]+(\d+)$", range_name)
        n = int(m.group(1))
        self.rows[n - 1] = [str(v) if v is not None else "" for v in values[0]]

    def delete_rows(self, n, *a, **kw):
        assert type(n) is int, f"delete_rows got {type(n)}"
        self._log("delete_rows", n=n)
        del self.rows[n - 1]


class FakeSpreadsheet:
    def __init__(self):
        self.ws = FakeWorksheet()

    def worksheets(self):
        return [self.ws]


class FakeClient:
    _ss = None

    def open_by_key(self, key):
        if FakeClient._ss is None:
            FakeClient._ss = FakeSpreadsheet()
        return FakeClient._ss


# ---------------------------------------------------------------------------
# requests.get stub: FX endpoints -> fixtures; CSV export -> snapshot; else refuse
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status_code=200, content=b"", json_data=None, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._json = json_data
        self.content = content if content else (
            json.dumps(json_data).encode("utf-8") if json_data is not None else b"")
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        if self._json is None:
            return json.loads(self.text)
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


def _ccy_from_url(url, params):
    if params and params.get("base"):
        return str(params["base"]).upper()
    m = re.search(r"/latest/([A-Za-z]{3})\b", url) or re.search(r"/currencies/([a-z]{3})\.min\.json", url)
    return m.group(1).upper() if m else "USD"


def _fx_answer(url, params):
    ccy = _ccy_from_url(url, params)
    rate = HARNESS_RATES.get(ccy)
    if rate is None:
        return FakeResp(404, json_data={"message": "not found"})
    if url.startswith(FX_ENDPOINTS["frankfurter"]):
        d = (params or {}).get("date") or HARNESS_DATE
        return FakeResp(json_data=[{"date": d, "base": ccy, "quote": "TWD", "rate": rate}])
    if "open.er-api.com" in url:
        return FakeResp(json_data={"result": "success", "time_eol_unix": 0,
                                   "time_last_update_unix": int(time.time()),
                                   "base_code": ccy, "rates": {"TWD": rate}})
    if "currency-api" in url:
        return FakeResp(json_data={"date": HARNESS_DATE, ccy.lower(): {"twd": rate}})
    return FakeResp(404, json_data={})


def _is_fx_url(url):
    return any(h in url for h in ("frankfurter", "open.er-api.com", "currency-api"))


def fake_get(url, *a, **kw):
    params = kw.get("params")
    if "docs.google.com" in url:
        return FakeResp(content=CSV_BYTES, content_type="text/csv")
    if _is_fx_url(url):
        if FX_MODE == "fail":
            raise requests.ConnectionError(f"harness: FX offline ({url})")
        if FX_MODE == "slow":
            time.sleep(FX_TIMEOUT_S)
            raise requests.Timeout(f"harness: FX timeout after {FX_TIMEOUT_S}s ({url})")
        return _fx_answer(url, params)
    raise requests.ConnectionError(f"harness: network refused ({url})")


requests.get = fake_get
if hasattr(requests, "api"):
    requests.api.get = fake_get

if MODE == "api":
    Credentials.from_service_account_info = staticmethod(lambda info, scopes=None: object())
    gspread.authorize = lambda creds: FakeClient()

runpy.run_path(os.path.join(REPO, "app.py"), run_name="__main__")
