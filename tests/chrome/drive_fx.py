"""
Scripted headless-Chrome scenarios for the 外幣換算 work (PLAN §5 steps 3-5).

    expense_env/bin/python tests/chrome/drive_fx.py login add_twd_domestic
    expense_env/bin/python tests/chrome/drive_fx.py all
    expense_env/bin/python tests/chrome/drive_fx.py --list

Each scenario boots the real app through ``runner.py`` (fake gspread, fake FX
endpoints — nothing leaves the machine), drives it in a 390x844 touch-emulated
Chrome, prints one structured line per check and saves screenshots under
``tests/chrome/out/``.

Output lines (grep-able):
    PASS <scenario> <check>
    FAIL <scenario> <check>: <detail>
    SKIP <scenario>: <reason>          (e.g. the FX card is not implemented yet)
    RESULT passed=N failed=N skipped=N
Exit status 1 when any check FAILed.

Scenarios and the runner environment they need:
    login             MODE=api                       PIN login -> three tabs
    add_twd_domestic  MODE=api                       台灣 row: no FX card, 金額 widget, blank J..L
    add_sgd           MODE=api FX_MODE=live          新加坡 -> SGD card, 12.5 -> NT$311, row written
    add_fx_fail       MODE=api FX_MODE=fail          every FX source down -> non-live caption, save works
    add_unmigrated    MODE=api FX_HEADERS=0          9-column sheet: caption + post-write warning
    edit_convert      MODE=api                       legacy 台灣 row -> 換算為外幣 opt-in, 保留原台幣金額
    edit_to_twd       MODE=api                       converted SGD row -> 幣別 TWD blanks J..L

Options:
    --st-port N   Streamlit port (default $ST_PORT or 8780)
    --cdp-port N  Chrome DevTools port (default $CDP_PORT or 9350)
    --attach URL  drive an already-running server instead of starting one
                  (its MODE/FX_MODE/FX_HEADERS are whatever you started it with)
    --env K=V     override a runner variable for every scenario (e.g. --env FX_MODE=slow)
    --desktop     1400x2400 window instead of the phone emulation
    --headed      show the browser (needs a display)
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from decimal import Decimal

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
for p in (HERE, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from helpers import q6, to_twd  # noqa: E402
from cdp import (Chrome, active_tab, click_button, click_tab, ensure_tab, fill_input,  # noqa: E402
                 input_value, select_option, select_option_containing, selectbox_value,
                 set_checkbox, widget_el, widget_present, OUT_DIR, ROOT)
from fxfixtures import HARNESS_RATES  # noqa: E402

PY = sys.executable
STREAMLIT = os.path.join(os.path.dirname(PY), "streamlit")
RUNNER = os.path.join(HERE, "runner.py")
LOGIN_USER = "菇菇"

TAB_ADD, TAB_EDIT, TAB_OVERVIEW = "➕ 新增", "✏️ 編輯", "📊 總覽"
FX_CARD_TITLE = "💱 外幣換算"
FX_OPTIN_PREFIX = "💱"          # plan: 「💱 換算為外幣」; current build: 「💱 以外幣輸入」
AMOUNT_RE = r"/^金額(\s|$)/"   # the in-form 金額 number_input (add: 「金額 💰」, edit: 「金額」)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.passed = self.failed = self.skipped = 0

    def ok(self, scenario, check, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"PASS {scenario} {check}")
        else:
            self.failed += 1
            print(f"FAIL {scenario} {check}: {detail}")
        return bool(cond)

    def skip(self, scenario, reason):
        self.skipped += 1
        print(f"SKIP {scenario}: {reason}")

    def summary(self):
        print(f"RESULT passed={self.passed} failed={self.failed} skipped={self.skipped}")
        return self.failed == 0


class Skip(Exception):
    pass


# ---------------------------------------------------------------------------
# Server + browser lifecycle
# ---------------------------------------------------------------------------
class Harness:
    def __init__(self, st_port, cdp_port, phone=True, headless=True, attach=None):
        self.st_port = st_port
        self.cdp_port = cdp_port
        self.phone = phone
        self.headless = headless
        self.attach = attach
        self.url = attach or f"http://localhost:{st_port}/"
        self.server = None
        self.server_env = None
        self.chrome = None
        self.write_log = None

    # -- streamlit server -------------------------------------------------
    def start_server(self, env):
        if self.attach:
            self.write_log = os.path.join(OUT_DIR, f"writes_{env.get('MODE', 'api')}.jsonl")
            return
        if self.server is not None and self.server_env == env:
            return
        self.stop_server()
        full = dict(os.environ)
        full.update(env)
        full["HARNESS_OUT"] = OUT_DIR
        self.write_log = os.path.join(OUT_DIR, f"writes_{env.get('MODE', 'api')}.jsonl")
        if os.path.exists(self.write_log):
            os.remove(self.write_log)
        log = open(os.path.join(OUT_DIR, f"streamlit_{self.st_port}.log"), "ab")
        self.server = subprocess.Popen(
            [STREAMLIT, "run", RUNNER, "--server.port", str(self.st_port), "--server.headless", "true",
             "--browser.gatherUsageStats", "false", "--server.fileWatcherType", "none"],
            cwd=REPO, env=full, stdout=log, stderr=subprocess.STDOUT)
        self.server_env = env
        for _ in range(150):
            try:
                with urllib.request.urlopen(f"http://localhost:{self.st_port}/_stcore/health", timeout=1) as r:
                    if r.read().strip() == b"ok":
                        break
            except Exception:
                pass
            if self.server.poll() is not None:
                raise RuntimeError(f"streamlit exited early; see {log.name}")
            time.sleep(0.2)
        else:
            raise RuntimeError("streamlit did not come up")
        print(f"# server up on :{self.st_port} env={env}")

    def stop_server(self):
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(10)
            except Exception:
                self.server.kill()
            self.server = None
            self.server_env = None

    # -- browser ------------------------------------------------------------
    async def open(self):
        if self.chrome is None:
            self.chrome = Chrome(port=self.cdp_port, phone=self.phone, headless=self.headless)
            await self.chrome.start(self.url)
        else:
            await self.chrome.navigate(self.url)
        await self.chrome.wait_idle(30)

    async def close(self):
        if self.chrome is not None:
            await self.chrome.stop()
            self.chrome = None

    async def login(self):
        """PIN login unless the cookie already logged us in. Returns True when the tabs are visible."""
        c = self.chrome
        if await c.eval("!!document.querySelector('[data-baseweb=\"tab\"]')"):
            return True
        await select_option(c, "用戶", LOGIN_USER)
        await c.click("document.querySelector('input[type=\"password\"]')")
        await c.type_text(config.FAMILY_PIN)
        await click_button(c, "🔓 登入")
        for _ in range(40):
            await asyncio.sleep(0.5)
            if await c.eval("!!document.querySelector('[data-baseweb=\"tab\"]')"):
                break
        await c.wait_idle(30)
        return bool(await c.eval("!!document.querySelector('[data-baseweb=\"tab\"]')"))

    async def fresh_session(self):
        """Reload -> new Streamlit session (session_state reset); the auth cookie keeps us logged in."""
        await self.open()
        return await self.login()

    # -- write log ------------------------------------------------------------
    def writes(self):
        if not self.write_log or not os.path.exists(self.write_log):
            return []
        with open(self.write_log, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Shared steps
# ---------------------------------------------------------------------------
async def no_exceptions(h, rep, name, check="no_exception"):
    exc = await h.chrome.exceptions()
    rep.ok(name, check, not exc, (exc[0][:300] if exc else ""))


async def goto_add_tab(h):
    await ensure_tab(h.chrome, TAB_ADD)


async def choose_country(h, country):
    c = h.chrome
    if await selectbox_value(c, "國家") != country:
        await select_option(c, "國家", country)
        await c.wait_idle(40)  # rate fetch happens in this rerun (spinner 取得匯率中…)


async def currency_select_present(h):
    return await widget_present(h.chrome, "stSelectbox", "幣別")


async def fx_card_present(h):
    """A conversion is active: the 原幣金額 number_input is on the page."""
    return await widget_present(h.chrome, "stNumberInput", "原幣金額")


async def amount_widget_present(h):
    """The plain in-form 金額 number_input (not 原幣金額 / 帳單金額)."""
    return bool(await h.chrome.eval(
        f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stNumberInput\"]'))"
        f".some(w=>{AMOUNT_RE}.test(w.innerText.trim()))"))


async def amount_widget_value(h):
    return await h.chrome.eval(
        f"(function(){{const w=Array.from({ROOT}.querySelectorAll('[data-testid=\"stNumberInput\"]'))"
        f".find(w=>{AMOUNT_RE}.test(w.innerText.trim())); if(!w) return null;"
        " const i=w.querySelector('input'); return i?i.value:null})()")


async def fill_amount_widget(h, text):
    c = h.chrome
    inp = (f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stNumberInput\"]'))"
           f".find(w=>{AMOUNT_RE}.test(w.innerText.trim())).querySelector('input')")
    await c.click(inp)
    await c.eval(f"(function(){{const i={inp}; i.select();}})()")
    await c.key("Backspace", "Backspace", 8)
    await c.type_text(text)


async def require_fx_card(h, rep, name):
    if not await fx_card_present(h):
        await h.chrome.screenshot(f"{name}_no_card.png")
        raise Skip("FX card (原幣金額 widget) not rendered — add-form FX not implemented yet or card hidden")


async def fx_optin_checkbox(h):
    """Label of the edit-form opt-in checkbox (starts with 💱), or None."""
    return await h.chrome.eval(
        f"(function(){{const w=Array.from({ROOT}.querySelectorAll('[data-testid=\"stCheckbox\"]'))"
        f".find(w=>w.innerText.trim().startsWith({json.dumps(FX_OPTIN_PREFIX)})); return w?w.innerText.trim():null}})()")


async def fill_add_form_and_submit(h, description, amount=None, fx_amount=None):
    c = h.chrome
    if fx_amount is not None:
        await fill_input(c, "原幣金額", fx_amount)
        await c.blur()
        await c.wait_idle(30)
    if amount is not None:
        await fill_amount_widget(h, amount)
    await fill_input(c, "描述", description, testid="stTextInput")
    await c.blur()
    await click_button(c, "💾 儲存支出")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_ADD)
    await c.wait_idle(10)


def last_write(h, op):
    ws = [w for w in h.writes() if w["op"] == op]
    return ws[-1] if ws else None


def fx_caption_text(panel):
    """Lines of the visible panel that look like the FX freshness caption."""
    return [l for l in panel.split("\n") if "匯率" in l and any(t in l for t in ("✅", "🕒", "🔁", "⚠️"))]


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
async def sc_login(h, rep):
    name = "login"
    await h.open()
    c = h.chrome
    has_form = await c.eval("!!document.querySelector('input[type=\"password\"]')")
    tabs_before = await c.eval("!!document.querySelector('[data-baseweb=\"tab\"]')")
    rep.ok(name, "landing_renders", has_form or tabs_before, "neither login form nor tabs")
    ok = await h.login()
    tabs = await c.eval("Array.from(document.querySelectorAll('[data-baseweb=\"tab\"]')).map(t=>t.innerText.trim())")
    rep.ok(name, "tabs_visible", ok and tabs == [TAB_ADD, TAB_EDIT, TAB_OVERVIEW], f"tabs={tabs}")
    rep.ok(name, "add_tab_first", await active_tab(c) == TAB_ADD, f"active={await active_tab(c)}")
    rep.ok(name, "no_horizontal_scroll", not await c.has_horizontal_scroll(), "page scrolls horizontally at 390px")
    await no_exceptions(h, rep, name)
    await c.screenshot("login_done.png")


async def sc_add_twd_domestic(h, rep):
    name = "add_twd_domestic"
    await h.fresh_session()
    c = h.chrome
    await goto_add_tab(h)
    await choose_country(h, "台灣")
    rep.ok(name, "country_taiwan", await selectbox_value(c, "國家") == "台灣", await selectbox_value(c, "國家"))
    rep.ok(name, "no_fx_conversion_widgets", not await fx_card_present(h) and not await c.metrics(),
           "原幣金額 / ≈ NT$ metric rendered for a 台灣 row")
    if await currency_select_present(h):
        print(f"# NOTE {name}: a 幣別 selectbox is rendered for 國家=台灣 (plan §2.1 says the card is not "
              f"rendered for domestic rows); value={await selectbox_value(c, '幣別')!r}")
    rep.ok(name, "amount_widget_present", await amount_widget_present(h), "in-form 金額 missing")
    before = len(h.writes())
    await fill_add_form_and_submit(h, "harness 午餐", amount="150")
    panel = await c.panel_text()
    rep.ok(name, "flash_success", "✅ 成功新增支出" in panel, panel[:300].replace("\n", " | "))
    w = last_write(h, "append_row")
    rep.ok(name, "row_appended", w is not None and len(h.writes()) > before, "no append_row logged")
    if w:
        v = w["values"]
        rep.ok(name, "amount_150_numeric", len(v) > 3 and v[3] == 150 and w["types"][3] in ("int", "float"),
               f"values[3]={v[3]!r} type={w['types'][3]}")
        rep.ok(name, "country_cell", len(v) > 6 and v[6] == "台灣", f"values[6]={v[6:8]}")
        if h.server_env is None or h.server_env.get("FX_HEADERS", "1") != "0":
            rep.ok(name, "fx_cells_blank", len(v) >= 12 and v[9:12] == ["", "", ""], f"J..L={v[9:12]}")
    rep.ok(name, "amount_widget_reset", (await amount_widget_value(h) or "") == "", await amount_widget_value(h))
    await no_exceptions(h, rep, name)
    await c.screenshot("add_twd_domestic.png")


async def sc_add_sgd(h, rep):
    name = "add_sgd"
    await h.fresh_session()
    c = h.chrome
    await goto_add_tab(h)
    await choose_country(h, "新加坡")
    await require_fx_card(h, rep, name)
    await c.screenshot("add_sgd_card.png")
    rep.ok(name, "currency_defaults_sgd", await selectbox_value(c, "幣別") == "SGD", await selectbox_value(c, "幣別"))
    rep.ok(name, "orig_amount_widget", await widget_present(c, "stNumberInput", "原幣金額"), "原幣金額 missing")
    # card + metric visible without scrolling under 地點 (PLAN §5 step 3)
    top = await c.eval("(function(){window.scrollTo(0,0);"
                       " const m=document.querySelector('[data-testid=\"stMetric\"]');"
                       " return m?m.getBoundingClientRect().top:null})()")
    rep.ok(name, "metric_rendered", top is not None, "no st.metric in the card")
    await fill_input(c, "原幣金額", "12.5")
    await c.blur()
    await c.wait_idle(30)
    rate = Decimal(str(HARNESS_RATES["SGD"]))
    expect_twd = to_twd(Decimal("12.5"), rate)
    metrics = await c.metrics()
    val = metrics[0][1] if metrics else ""
    digits = "".join(ch for ch in val if ch.isdigit())
    rep.ok(name, "metric_twd", digits == str(expect_twd), f"metric={metrics} expected NT${expect_twd}")
    panel = await c.panel_text()
    caps = fx_caption_text(panel)
    # the quote is fetched on the 國家 rerun; by the time the amount is typed it is 🕒 快取 (still Frankfurter)
    rep.ok(name, "caption_live_source", any(("✅" in l or "🕒" in l) and "Frankfurter" in l for l in caps),
           f"captions={caps}")
    rep.ok(name, "caption_rate", any(f"{rate:.4f}" in l or str(rate) in l for l in caps), f"captions={caps}")
    rep.ok(name, "in_form_amount_hidden", not await amount_widget_present(h),
           "金額 number_input still rendered in FX mode")
    rep.ok(name, "in_form_amount_info", "金額 (TWD)" in panel and f"NT${expect_twd}" in panel.replace(",", ""),
           [l for l in panel.split("\n") if "金額" in l][:3])
    # PLAN §5 step 3: "card + metric visible without scroll under 地點" -> once 地點 is at the top of
    # the phone screen, the metric bottom must be within the same 844 px viewport.
    span = await c.eval(
        f"(function(){{const l={widget_el('stSelectbox', '地點')}; const m={ROOT}.querySelector('[data-testid=\"stMetric\"]');"
        " if(!l||!m) return null; return [l.getBoundingClientRect().top, m.getBoundingClientRect().bottom];})()")
    dist = (span[1] - span[0]) if span else None
    rep.ok(name, "metric_within_viewport_of_location", dist is not None and dist <= 844,
           f"地點 top -> metric bottom = {dist}px (viewport 844)")
    await c.screenshot("add_sgd_filled.png")
    await fill_add_form_and_submit(h, "harness SGD 咖啡")
    panel = await c.panel_text()
    rep.ok(name, "flash_success", "✅ 成功新增支出" in panel and "SGD" in panel, panel[:300].replace("\n", " | "))
    w = last_write(h, "append_row")
    rep.ok(name, "row_appended", w is not None, "no append_row logged")
    if w:
        v = w["values"]
        rep.ok(name, "row_width_12", len(v) >= 12, f"len={len(v)}")
        if len(v) >= 12:
            rep.ok(name, "currency_cell", v[9] == "SGD", f"J={v[9]!r}")
            rep.ok(name, "orig_amount_cell", v[10] == "12.50", f"K={v[10]!r}")
            try:
                stored_rate = Decimal(str(v[11]))
            except Exception:
                stored_rate = None
            rep.ok(name, "rate_cell_6dp", stored_rate is not None and stored_rate == q6(rate), f"L={v[11]!r}")
            rep.ok(name, "amount_matches_to_twd", v[3] == expect_twd, f"D={v[3]!r} expected {expect_twd}")
    rep.ok(name, "orig_amount_reset", (await input_value(c, "原幣金額") or "") == "" if await fx_card_present(h) else True,
           await input_value(c, "原幣金額"))
    rep.ok(name, "currency_persists", await selectbox_value(c, "幣別") == "SGD" if await fx_card_present(h) else False,
           await selectbox_value(c, "幣別"))
    await no_exceptions(h, rep, name)
    await c.screenshot("add_sgd_saved.png")


async def sc_add_fx_fail(h, rep):
    name = "add_fx_fail"
    await h.fresh_session()
    c = h.chrome
    await goto_add_tab(h)
    await choose_country(h, "新加坡")
    await require_fx_card(h, rep, name)
    panel = await c.panel_text()
    caps = fx_caption_text(panel)
    rep.ok(name, "caption_not_live", caps and not any("✅" in l for l in caps), f"captions={caps}")
    rep.ok(name, "caption_fallback_state", any(("🔁" in l or "⚠️" in l or "🕒" in l) for l in caps), f"captions={caps}")
    await c.screenshot("add_fx_fail_card.png")
    await fill_add_form_and_submit(h, "harness 離線 SGD", fx_amount="10")
    panel = await c.panel_text()
    rep.ok(name, "save_still_possible", "✅ 成功新增支出" in panel, panel[:300].replace("\n", " | "))
    w = last_write(h, "append_row")
    if rep.ok(name, "row_appended", w is not None and len(w["values"]) >= 12, "no 12-wide append_row logged"):
        v = w["values"]
        rep.ok(name, "currency_cell", v[9] == "SGD", f"J={v[9]!r}")
        try:
            r = Decimal(str(v[11]))
        except Exception:
            r = None
        rep.ok(name, "rate_positive", r is not None and r > 0, f"L={v[11]!r}")
        if r:
            rep.ok(name, "amount_matches_rate", v[3] == to_twd(Decimal("10"), r), f"D={v[3]!r} rate={r}")
    await no_exceptions(h, rep, name)
    await c.screenshot("add_fx_fail_saved.png")


async def sc_add_unmigrated(h, rep):
    name = "add_unmigrated"
    await h.fresh_session()
    c = h.chrome
    await goto_add_tab(h)
    await choose_country(h, "新加坡")
    await require_fx_card(h, rep, name)
    panel = await c.panel_text()
    rep.ok(name, "pre_submit_caption", "工作表尚未新增幣別欄位" in panel,
           [l for l in panel.split("\n") if "工作表" in l][:3])
    await c.screenshot("add_unmigrated_card.png")
    await fill_add_form_and_submit(h, "harness 未遷移 SGD", fx_amount="10")
    panel = await c.panel_text()
    rep.ok(name, "flash_success", "✅ 成功新增支出" in panel, panel[:300].replace("\n", " | "))
    rep.ok(name, "post_write_warning", "工作表尚未有" in panel or "已略過" in panel,
           [l for l in panel.split("\n") if "工作表" in l or "略過" in l][:3])
    w = last_write(h, "append_row")
    if rep.ok(name, "row_appended", w is not None, "no append_row logged"):
        v = w["values"]
        rep.ok(name, "row_width_9", len(v) == 9, f"len={len(v)} values={v}")
        rep.ok(name, "twd_amount_saved", isinstance(v[3], (int, float)) and v[3] > 0, f"D={v[3]!r}")
    await no_exceptions(h, rep, name)
    await c.screenshot("add_unmigrated_saved.png")


async def sc_edit_convert(h, rep):
    name = "edit_convert"
    await h.fresh_session()
    c = h.chrome
    await ensure_tab(c, TAB_EDIT)
    await select_option_containing(c, "選擇要編輯的支出記錄", "今日午餐")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    rep.ok(name, "legacy_row_amount_widget", await amount_widget_present(h), "金額 widget missing")
    rep.ok(name, "legacy_row_no_card", not await fx_card_present(h) and not await currency_select_present(h),
           "FX card shown for a legacy TWD row")
    optin = await fx_optin_checkbox(h)
    if optin is None:
        await c.screenshot(f"{name}_no_optin.png")
        raise Skip("opt-in checkbox (💱 …) not rendered — edit-form FX not implemented yet")
    optin_checked = await c.eval(f"({widget_el('stCheckbox', optin)}).querySelector('input').checked")
    rep.ok(name, "optin_default_off", not optin_checked, "opt-in ticked by default on a legacy row")
    await set_checkbox(c, optin, True)
    await c.wait_idle(40)
    await ensure_tab(c, TAB_EDIT)
    if not await currency_select_present(h):
        await c.screenshot(f"{name}_no_currency.png")
        raise Skip("幣別 selectbox not rendered after opting in — edit-form FX card missing")
    # a 台灣 row defaults to TWD (plan §2.5: stored currency wins, else COUNTRY_CURRENCY) -> pick SGD
    if await selectbox_value(c, "幣別") != "SGD":
        await select_option(c, "幣別", "SGD")
        await c.wait_idle(40)
        await ensure_tab(c, TAB_EDIT)
    await require_fx_card(h, rep, name)
    await fill_input(c, "原幣金額", "6")
    await c.blur()
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    keep_present = await widget_present(c, "stCheckbox", "保留原台幣金額")
    rep.ok(name, "keep_twd_checkbox", keep_present, "保留原台幣金額 checkbox missing")
    if keep_present:
        checked = await c.eval(f"({widget_el('stCheckbox', '保留原台幣金額')}).querySelector('input').checked")
        rep.ok(name, "keep_twd_default_on", bool(checked), "expected ON for a back-fill of an existing 金額")
    await c.screenshot("edit_convert_card.png")
    await click_button(c, "💾 更新")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    panel = await c.panel_text()
    rep.ok(name, "flash_updated", "✅ 已更新支出" in panel, panel[:300].replace("\n", " | "))
    w = last_write(h, "update")
    if rep.ok(name, "update_written", w is not None, "no update logged"):
        v = w["values"][0]
        rep.ok(name, "row_width_12", len(v) >= 12, f"len={len(v)}")
        if len(v) >= 12:
            rep.ok(name, "amount_unchanged_150", v[3] == 150, f"D={v[3]!r}")
            rep.ok(name, "currency_sgd", v[9] == "SGD", f"J={v[9]!r}")
            rep.ok(name, "orig_amount", v[10] == "6.00", f"K={v[10]!r}")
            rep.ok(name, "rate_derived", v[11] == "25" or Decimal(str(v[11] or 0)) == Decimal("25"), f"L={v[11]!r}")
    await no_exceptions(h, rep, name)
    await c.screenshot("edit_convert_saved.png")


async def sc_edit_to_twd(h, rep):
    name = "edit_to_twd"
    await h.fresh_session()
    c = h.chrome
    await ensure_tab(c, TAB_EDIT)
    try:
        await select_option_containing(c, "選擇要編輯的支出記錄", "新加坡咖啡")
    except RuntimeError as e:
        raise Skip(f"converted seed row not listed (FX_HEADERS=0?): {e}")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    await require_fx_card(h, rep, name)
    rep.ok(name, "currency_prefilled", await selectbox_value(c, "幣別") == "SGD", await selectbox_value(c, "幣別"))
    rep.ok(name, "orig_prefilled", (await input_value(c, "原幣金額") or "").replace(",", "").startswith("12.5"),
           await input_value(c, "原幣金額"))
    rep.ok(name, "amount_hidden", not await amount_widget_present(h), "金額 widget shown beside the card")
    await c.screenshot("edit_to_twd_card.png")
    await select_option(c, "幣別", "TWD")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    rep.ok(name, "amount_returns", await amount_widget_present(h), "金額 widget did not return")
    await click_button(c, "💾 更新")
    await c.wait_idle(30)
    await ensure_tab(c, TAB_EDIT)
    panel = await c.panel_text()
    rep.ok(name, "flash_updated", "✅ 已更新支出" in panel, panel[:300].replace("\n", " | "))
    w = last_write(h, "update")
    if rep.ok(name, "update_written", w is not None, "no update logged"):
        v = w["values"][0]
        rep.ok(name, "fx_cells_blanked", len(v) >= 12 and v[9:12] == ["", "", ""], f"J..L={v[9:12] if len(v) >= 12 else v}")
        rep.ok(name, "amount_kept", v[3] == 311, f"D={v[3]!r}")
    await no_exceptions(h, rep, name)
    await c.screenshot("edit_to_twd_saved.png")


SCENARIOS = {
    "login": (sc_login, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}),
    "add_twd_domestic": (sc_add_twd_domestic, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}),
    "add_sgd": (sc_add_sgd, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}),
    "add_fx_fail": (sc_add_fx_fail, {"MODE": "api", "FX_MODE": "fail", "FX_HEADERS": "1"}),
    "add_unmigrated": (sc_add_unmigrated, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "0"}),
    "edit_convert": (sc_edit_convert, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}),
    "edit_to_twd": (sc_edit_to_twd, {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}),
}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(names, h):
    rep = Report()
    try:
        for name in names:
            fn, env = SCENARIOS[name]
            env = {**env, **getattr(h, "overrides", {})}
            try:
                h.start_server(env)
                if h.server_env is not None and h.chrome is not None and env != getattr(h, "_last_env", env):
                    await h.close()  # new server -> fresh browser (old websocket is dead anyway)
                h._last_env = env
                if h.chrome is None:
                    await h.open()
                await fn(h, rep)
            except Skip as s:
                rep.skip(name, str(s))
            except Exception as e:  # a crashed scenario is a FAIL, not a harness abort
                rep.ok(name, "scenario_completed", False, f"{type(e).__name__}: {e}")
                try:
                    await h.chrome.screenshot(f"{name}_error.png")
                except Exception:
                    pass
            errs = h.chrome.console_errors() if h.chrome else []
            if errs:
                print(f"# {name} console errors: {errs[:5]}")
                h.chrome.events.clear()
    finally:
        await h.close()
        h.stop_server()
    return rep.summary()


def main(argv):
    args = list(argv)
    st_port = int(os.environ.get("ST_PORT", "8780"))
    cdp_port = int(os.environ.get("CDP_PORT", "9350"))
    attach = None
    phone, headless = True, True
    names = []
    overrides = {}
    while args:
        a = args.pop(0)
        if a == "--list":
            for k, (_, env) in SCENARIOS.items():
                print(f"{k:18s} {env}")
            return 0
        elif a == "--st-port":
            st_port = int(args.pop(0))
        elif a == "--cdp-port":
            cdp_port = int(args.pop(0))
        elif a == "--attach":
            attach = args.pop(0)
        elif a == "--env":
            k, _, v = args.pop(0).partition("=")
            overrides[k] = v
        elif a == "--desktop":
            phone = False
        elif a == "--headed":
            headless = False
        elif a == "all":
            names.extend(SCENARIOS.keys())
        elif a in SCENARIOS:
            names.append(a)
        else:
            print(f"unknown scenario/option {a!r}; known: {', '.join(SCENARIOS)}")
            return 2
    if not names:
        print(__doc__)
        return 2
    h = Harness(st_port, cdp_port, phone=phone, headless=headless, attach=attach)
    h.overrides = overrides
    ok = asyncio.run(run(names, h))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
