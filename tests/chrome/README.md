# Headless-Chrome harness (`tests/chrome/`)

Drives the **real** `app.py` in a real Chrome (390×844 phone emulation, touch
enabled) with Google Sheets and every FX endpoint stubbed. Nothing leaves the
machine: gspread is replaced by an in-memory worksheet, `requests.get` answers
FX URLs from local tables and refuses any other host.

Used for PLAN_fx_and_overview.md §5 step 3/4/5 acceptance ("Headless Chrome
390 px: card + metric visible without scroll under 地點", later the 總覽 layout
checks) and for anything AppTest cannot see (BaseWeb dropdowns, layout, scroll).

| File | Role |
|---|---|
| `runner.py` | Streamlit entry point: stubs gspread/requests, then runs `app.py`. Env: `MODE`, `FX_HEADERS`, `FX_MODE`. Logs every sheet write to `out/writes_<MODE>.jsonl`. |
| `cdp.py` | Minimal Chrome DevTools driver (tornado websocket): `Chrome(port)`, `start/stop`, `eval`, `click/tap/type_text/key/blur`, `wait_idle`, `screenshot` (full page), `page_text/panel_text/metrics/exceptions/alerts/console_errors`, and Streamlit widget helpers `select_option`, `select_option_containing`, `fill_input`, `input_value`, `set_checkbox`, `click_button`, `click_tab`, `ensure_tab`, `open_expander`, `widget_present`, `selectbox_value`. All lookups are scoped to the **visible** tab panel (`ROOT`). |
| `drive_fx.py` | Scenario runner: starts a server per required env, one Chrome, PIN login, prints `PASS/FAIL/SKIP` lines, screenshots to `out/`. |
| `fxfixtures.py` | Rates the fake FX sources answer with (`HARNESS_RATES`, SGD = 24.908 like `tests/fixtures/frankfurter.json`) and the seeded converted row. |
| `out/` | Screenshots, write logs, Chrome/Streamlit logs, Chrome profile. Git-ignored. |

## Run

```bash
cd /home/ythuang/YTH_personal/expense-dashboard
expense_env/bin/python tests/chrome/drive_fx.py login add_twd_domestic   # smoke
expense_env/bin/python tests/chrome/drive_fx.py all                      # every scenario
expense_env/bin/python tests/chrome/drive_fx.py --list                   # names + env
expense_env/bin/python tests/chrome/drive_fx.py --env FX_MODE=slow add_sgd   # override runner env
```

Ports: Streamlit `$ST_PORT`/`--st-port` (default 8780), CDP `$CDP_PORT`/`--cdp-port`
(default 9350). Use free ports ≥ 8780 / ≥ 9350 when running in parallel.
Chrome binary: `/opt/google/chrome/chrome` (override with `CHROME_BIN`).
`--desktop` = 1400×2400 window, `--headed` = visible browser, `--attach URL` =
drive a server you started yourself (see below).

Exit status is 1 when any check FAILed. Output format:

```
PASS <scenario> <check>
FAIL <scenario> <check>: <detail>
SKIP <scenario>: <reason>       # e.g. FX card not implemented yet — never a crash
# NOTE ...                       # informational (not counted)
RESULT passed=N failed=N skipped=N
```

## Scenarios

| Name | Runner env | What it checks |
|---|---|---|
| `login` | api/live/headers | login form → 菇菇 + PIN → tabs `➕ 新增` first; no horizontal scroll at 390 px |
| `add_twd_domestic` | api/live/headers | 國家=台灣: no 原幣金額 / metric, plain 金額 widget; 150 saved as a number, J..L blank, widget reset |
| `add_sgd` | api/live/headers | 國家=新加坡 → 幣別 SGD, type 12.5 → metric NT$311, caption ✅/🕒 Frankfurter, in-form 金額 replaced by the info line, 地點→metric within one viewport; row: `SGD`, `12.50`, `24.908`, 311; 原幣金額 cleared and 幣別 kept after save |
| `add_fx_fail` | `FX_MODE=fail` | every source down → caption 🔁/⚠️/🕒 (never ✅); save still works with a positive rate and `amount == to_twd(orig, rate)` |
| `add_unmigrated` | `FX_HEADERS=0` | 9-column sheet: pre-submit caption 「工作表尚未新增幣別欄位」, TWD row written (9 cells), post-write warning |
| `edit_convert` | api/live/headers | legacy 台灣 row (今日午餐, 150): 金額 widget + no card; opt-in checkbox (💱…) off by default → 幣別 SGD → 原幣金額 6 → 保留原台幣金額 ON → update writes 150 / SGD / 6.00 / 25 |
| `edit_to_twd` | api/live/headers | seeded converted row (新加坡咖啡 SGD 12.50): card prefilled, 金額 hidden; 幣別→TWD brings 金額 back; update writes `''` for J..L, 311 kept |

Scenarios that need a UI element that is not implemented yet print `SKIP`
(and save `<scenario>_no_card.png`) instead of failing, so the harness is usable
before the forms work lands.

## Runner environment (`runner.py`)

| Var | Values | Effect |
|---|---|---|
| `MODE` | `api` (default) / `csv` | fake gspread (writable) / gspread init fails as with placeholder secrets → CSV export fallback (read-only, served from `new_to_fill.csv`) |
| `FX_HEADERS` | `1` (default) / `0` | header row `A..L` with 幣別 原幣金額 匯率 (+ one converted seed row) / legacy 9 columns |
| `FX_MODE` | `live` (default) / `fail` / `slow` | fake sources answer (Frankfurter first) / every FX call raises `ConnectionError` / every FX call sleeps `FX_TIMEOUT_S` then raises `Timeout` (worst case ≈ 12 s per quote, G9) |
| `HARNESS_OUT` | path | where the write log goes (drive_fx sets it to `tests/chrome/out`) |

Seed = first 40 rows of `new_to_fill.csv` + adversarial rows (duplicate, bad
amount, refund, empty, ISO date, bad date, unknown account) + `今日午餐` 150
(台灣) + `新加坡咖啡` SGD 12.50 @ 24.908 = 311 (only with `FX_HEADERS=1`).

Write log line: `{"t": ..., "op": "append_row"|"update"|"delete_rows", "values": [...], "types": [...], "range_name": ...}`.

### Driving a server by hand

```bash
MODE=api FX_MODE=fail HARNESS_OUT=tests/chrome/out \
  expense_env/bin/streamlit run tests/chrome/runner.py --server.port 8781 --server.headless true
expense_env/bin/python tests/chrome/drive_fx.py --attach http://localhost:8781/ --cdp-port 9351 add_fx_fail
```

## Writing a new scenario

```python
async def sc_overview_layout(h, rep):
    name = "overview_layout"
    await h.fresh_session()              # reload = new session_state, cookie keeps the login
    c = h.chrome
    await ensure_tab(c, TAB_OVERVIEW)
    rep.ok(name, "first_metric_y_lt_400", (await c.eval(
        f"({ROOT}).querySelector('[data-testid=\"stMetric\"]').getBoundingClientRect().top")) < 400)
    rep.ok(name, "page_height", await c.page_height() <= 2300, await c.page_height())
    rep.ok(name, "no_hscroll", not await c.has_horizontal_scroll())
    await c.screenshot("overview.png")

SCENARIOS["overview_layout"] = (sc_overview_layout, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"})
```

Rules of thumb: after any outside-form widget change call `await c.wait_idle(30)`
then `await ensure_tab(c, ...)` (a rerun can bounce the active tab); commit an
`st.number_input` with `await c.blur()`; assert on `h.writes()` rather than on
the UI when the question is "what reached the sheet".

## Cleanup

`drive_fx.py` stops its own Streamlit and Chrome. If a run was interrupted:

```bash
kill $(pgrep -f "tests/chrome/runner.py") $(pgrep -f "remote-debugging-port=9350") 2>/dev/null
```
