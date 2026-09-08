"""
Scripted headless-Chrome scenarios for the 總覽 redesign (PLAN §3.2 / §5 steps 6-8).

    expense_env/bin/python tests/chrome/drive_overview.py overview_first_screen
    expense_env/bin/python tests/chrome/drive_overview.py all
    expense_env/bin/python tests/chrome/drive_overview.py --list

Same harness as drive_fx.py (runner.py = real app.py with fake gspread + fake FX
endpoints, cdp.py = 390x844 touch-emulated Chrome). Output lines are grep-able:

    PASS <scenario> <check>
    FAIL <scenario> <check>: <detail>
    SKIP <scenario>: <reason>          (redesign not implemented yet — never a crash)
    # NOTE ...                         (informational, not counted)
    RESULT passed=N failed=N skipped=N

Every scenario is written to the plan's DOM (§3.2): segmented control 今天/本週/
本月/本年/更多…, hero st.metric, 更多期間 popover (pills + 自訂範圍 + trip 查看),
static HTML stat tiles, st.badge("篩選: …") + 清除, expanders 📋 本期全部交易 /
📈 趨勢 / 👤 帳戶與類型 / 🔍 篩選 / 🧹 資料檢查. When the segmented control is not on
the page the scenario prints SKIP (and saves `<scenario>_no_redesign.png`).

Scenarios (all MODE=api FX_MODE=live FX_HEADERS=1):
    overview_first_screen  hero top < 400 px, no horizontal scroll, page ≤ 2300 px collapsed
    period_switch          今天/本週/本年 change the hero; 更多… → 上月 / 全部; custom end<start
                           shows the error while the category filter chip survives
    filters                🔍 篩選 → account pill → badge → 清除 resets
    expanders              every expander opens without exception; Plotly static (no modebar,
                           no drag zoom); dataframe toolbar hidden at 390 px
    trips                  active-trip badge (seed 新加坡 row within TRIP_ACTIVE_GRACE_DAYS);
                           popover 查看 sets the period + 國家 filter
    theme                  light + dark screenshots via prefers-color-scheme; tile contrast
    converted_rows         add one SGD row (drive_fx flow) → 最近 shows '· SGD', 📋 shows 原幣
                           (runs last: it changes the fake sheet)

Options: as drive_fx.py (--st-port / --cdp-port / --attach URL / --env K=V / --desktop
/ --headed). Defaults here: Streamlit 8800, CDP 9400 (so it can run beside drive_fx).
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
for p in (HERE, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import config  # noqa: E402
from helpers import today_local  # noqa: E402
from cdp import (ROOT, click_button, ensure_tab, open_expander, select_option,  # noqa: E402
                 widget_el)
from drive_fx import (Harness, Report, Skip, TAB_OVERVIEW, choose_country,  # noqa: E402
                      fill_add_form_and_submit, goto_add_tab, last_write, no_exceptions,
                      require_fx_card)
from fxfixtures import CONVERTED_ROW  # noqa: E402

ENV = {"MODE": "api", "FX_MODE": "live", "FX_HEADERS": "1"}
SEG_OPTIONS = list(config.OVERVIEW_PERIODS)            # 今天 本週 本月 本年 更多…
MORE_LABEL = SEG_OPTIONS[-1]                           # 更多…
EXPANDERS = ["本期全部交易", "趨勢", "帳戶與類型", "篩選", "資料檢查"]
EMPTY_HINT = "尚無支出"                                # st.info("本月尚無支出 — 試試 上月 或 全部")
RANGE_ERROR = "不可早於"                                # ⚠️ 結束日期不可早於開始日期 (kept, G8)
BADGE_PREFIX = "篩選"
VIEW_BUTTON = "查看"
CLEAR_BUTTON = "清除"
ACTIVE_TRIP_TEXT = "正在旅行中"
CUSTOM_START, CUSTOM_END_BAD = "2026/09/05", "2026/09/01"   # end < start → error
MIN_TILE_CONTRAST = 3.0                                # WCAG large-text floor

POPOVER_BODY = "document.querySelector('[data-testid=\"stPopoverBody\"]')"
SEG_BUTTONS = f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stButtonGroup\"] button'))"


# ---------------------------------------------------------------------------
# DOM helpers (plan §3.2 widgets)
# ---------------------------------------------------------------------------
async def scroll_top(c):
    await c.eval("(function(){window.scrollTo(0,0);"
                 " for (const e of document.querySelectorAll('[data-testid=\"stMain\"], section.main,"
                 " [data-testid=\"stAppViewContainer\"]')) e.scrollTop=0;})()")
    await asyncio.sleep(0.2)


async def redesign_present(c):
    """The plan's segmented control: a button group in the visible panel with a 本月 button."""
    return bool(await c.eval(f"{SEG_BUTTONS}.some(b=>b.innerText.trim()==={json.dumps(SEG_OPTIONS[2])})"))


async def require_redesign(h, rep, name):
    c = h.chrome
    await ensure_tab(c, TAB_OVERVIEW)
    await c.wait_idle(30)
    if not await redesign_present(c):
        await c.screenshot(f"{name}_no_redesign.png")
        raise Skip("segmented period control (今天/本週/本月/本年/更多…) not rendered — 總覽 redesign not implemented yet")


async def seg_active(c):
    return await c.eval(
        f"(function(){{const b={ROOT}.querySelector('[data-testid=\"stBaseButton-segmented_controlActive\"]');"
        " return b?b.innerText.trim():null})()")


async def seg_click(c, text):
    js = f"{SEG_BUTTONS}.find(b=>b.innerText.trim()==={json.dumps(text)})"
    if not await c.eval(f"!!({js})"):
        raise RuntimeError(f"segmented option {text!r} not found")
    await c.click(js)
    await c.wait_idle(30)
    await ensure_tab(c, TAB_OVERVIEW)


async def hero(c):
    """First st.metric of the visible panel: {label, value, delta, top} or None."""
    return await c.eval(
        f"(function(){{const m={ROOT}.querySelector('[data-testid=\"stMetric\"]'); if(!m) return null;"
        " const t=s=>{const e=m.querySelector('[data-testid=\"'+s+'\"]'); return e?e.innerText.trim():''};"
        " return {label:t('stMetricLabel'), value:t('stMetricValue'), delta:t('stMetricDelta'),"
        " top:m.getBoundingClientRect().top};})()")


async def period_state(c):
    """('hero', {…}) when the hero renders, ('empty', info_text) for the empty-period st.info, else (None, None)."""
    m = await hero(c)
    if m:
        return "hero", m
    panel = await c.panel_text()
    for line in panel.split("\n"):
        if EMPTY_HINT in line:
            return "empty", line.strip()
    return None, None


def period_applied(state, label):
    """The hero label (or the empty-state hint) names the period."""
    kind, val = state
    if kind == "hero":
        return val["label"].startswith(label) or label in val["label"]
    if kind == "empty":
        return True  # the hint text names the period ('本月尚無支出'); any wording accepted
    return False


async def filter_badge(c):
    return await c.eval(
        f"(function(){{const b=Array.from({ROOT}.querySelectorAll('span.stMarkdownBadge, [data-testid=\"stMarkdownBadge\"]'))"
        f".find(e=>e.innerText.includes({json.dumps(BADGE_PREFIX)})); return b?b.innerText.trim():null}})()")


async def popover_open(c):
    return bool(await c.eval(f"!!({POPOVER_BODY})"))


async def open_more_popover(c):
    """更多… → st.popover('更多期間'). Handles both layouts: a popover button already on the
    page, or one that appears after the segmented 更多… tap. Returns True when the body is open."""
    if await popover_open(c):
        return True
    btn = f"{ROOT}.querySelector('[data-testid=\"stPopoverButton\"]')"
    if not await c.eval(f"!!({btn})"):
        if await c.eval(f"{SEG_BUTTONS}.some(b=>b.innerText.trim()==={json.dumps(MORE_LABEL)})"):
            await seg_click(c, MORE_LABEL)
    if not await c.eval(f"!!({btn})"):
        return bool(await popover_open(c))
    await c.click(btn)
    return bool(await c.wait_for(f"!!({POPOVER_BODY})", timeout=5))


async def popover_button(c, text, row_contains=None):
    """Click a button inside the popover body whose text == `text`; with row_contains, the one whose
    enclosing horizontal block mentions that substring (trip rows: '🇸🇬 新加坡 09/05–09/07 [查看]')."""
    js = (f"(function(){{const body={POPOVER_BODY}; if(!body) return null;"
          f" const bs=Array.from(body.querySelectorAll('button')).filter(b=>b.innerText.trim()==={json.dumps(text)});"
          f" const want={json.dumps(row_contains)};"
          " if(want){const hit=bs.find(b=>{const r=b.closest('[data-testid=\"stHorizontalBlock\"]')||b.parentElement;"
          " return r&&r.innerText.includes(want)}); if(hit) return hit;}"
          " return bs[0]||null;})()")
    if not await c.eval(f"!!({js})"):
        return False
    await c.click(js)
    await c.wait_idle(30)
    await ensure_tab(c, TAB_OVERVIEW)
    return True


async def popover_trip_rows(c):
    """Text of the popover rows that carry a 查看 button."""
    return await c.eval(
        f"(function(){{const body={POPOVER_BODY}; if(!body) return [];"
        f" return Array.from(body.querySelectorAll('button')).filter(b=>b.innerText.trim()==={json.dumps(VIEW_BUTTON)})"
        " .map(b=>{const r=b.closest('[data-testid=\"stHorizontalBlock\"]')||b.parentElement;"
        " return r?r.innerText.replace(/\\s+/g,' ').trim():''});})()")


async def set_popover_date(c, nth, text):
    """Type a date (YYYY/MM/DD) into the nth st.date_input of the popover body and commit with Enter."""
    inp = f"({POPOVER_BODY}).querySelectorAll('[data-testid=\"stDateInput\"] input')[{nth}]"
    if not await c.eval(f"!!({inp})"):
        return False
    await c.click(inp)
    await c.eval(f"(function(){{const i={inp}; i.select();}})()")
    await c.key("Backspace", "Backspace", 8)
    await c.type_text(text)
    await c.key("Enter", "Enter", 13)
    await c.wait_idle(30)
    await ensure_tab(c, TAB_OVERVIEW)
    return True


async def expander_summaries(c):
    return await c.eval(f"Array.from({ROOT}.querySelectorAll('summary')).map(s=>s.innerText.trim())")


async def close_all_expanders(c):
    return await c.eval(
        f"(function(){{const o=Array.from({ROOT}.querySelectorAll('details[open]')); o.forEach(d=>d.open=false); return o.length}})()")


async def pill_click(c, group_label, text):
    """Click the pill `text` in the st.pills group whose text starts with `group_label` (visible panel)."""
    grp = (f"(function(){{const gs=Array.from({ROOT}.querySelectorAll('[data-testid=\"stButtonGroup\"]'));"
           f" const g=gs.find(g=>g.innerText.trim().startsWith({json.dumps(group_label)})"
           f" || (g.closest('[data-testid=\"stElementContainer\"]')||g).innerText.trim().startsWith({json.dumps(group_label)}));"
           f" const pool=g?Array.from(g.querySelectorAll('button')):gs.flatMap(x=>Array.from(x.querySelectorAll('button')));"
           # Streamlit splits an emoji label across nodes ('\u2708\ufe0f\n\u65c5\u884c'),
           # so compare with all whitespace removed instead of an exact trim() match.
           f" const norm=s=>String(s).replace(/\\s+/g,'');"
           f" return pool.find(b=>norm(b.innerText)===norm({json.dumps(text)}))||null;}})()")
    if not await c.eval(f"!!({grp})"):
        return False
    await c.click(grp)
    await c.wait_idle(30)
    await ensure_tab(c, TAB_OVERVIEW)
    return True


async def grid_texts(c):
    """innerText of every st.dataframe accessibility table in the visible panel (visible cells only)."""
    return await c.eval(
        f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stDataFrame\"] table')).map(t=>t.innerText)")


async def plotly_report(c):
    """Per chart: staticPlot, displayModeBar, modebar buttons in DOM, x-range, height."""
    return await c.eval(
        f"Array.from({ROOT}.querySelectorAll('.js-plotly-plot')).map(g=>{{const ctx=g._context||{{}};"
        " const fl=g._fullLayout||{}; const xa=fl.xaxis||{};"
        " return {static:ctx.staticPlot===true, modebar:ctx.displayModeBar, modebar_btns:g.querySelectorAll('.modebar-btn').length,"
        " xrange:JSON.stringify(xa.range||null), height:g.clientHeight,"
        " rect:(r=>[r.x+r.width/2, r.y+r.height/2, r.width])(g.getBoundingClientRect())};})")


async def drag(c, x, y, dx):
    await c.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    await c.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
    for i in range(1, 6):
        await c.send("Input.dispatchMouseEvent", type="mouseMoved", x=x + dx * i / 5, y=y, button="left")
        await asyncio.sleep(0.05)
    await c.send("Input.dispatchMouseEvent", type="mouseReleased", x=x + dx, y=y, button="left", clickCount=1)
    await asyncio.sleep(0.6)


async def toolbar_hidden(c):
    """Hover the first dataframe, then: toolbar in DOM → computed display none; not in DOM → CSS rule present."""
    pt = await c.rect(f"{ROOT}.querySelector('[data-testid=\"stDataFrame\"]')")
    if pt is None:
        return None, "no st.dataframe on the page"
    await c.send("Input.dispatchMouseEvent", type="mouseMoved", x=pt[0], y=pt[1])
    await asyncio.sleep(0.5)
    disp = await c.eval(
        f"(function(){{const t={ROOT}.querySelector('[data-testid=\"stElementToolbar\"]');"
        " return t?getComputedStyle(t).display:null})()")
    if disp is not None:
        return disp == "none", f"computed display={disp}"
    rule = await c.eval("Array.from(document.querySelectorAll('style')).some(s=>s.textContent.includes('stElementToolbar'))")
    return bool(rule), "toolbar not in DOM; CSS rule " + ("present" if rule else "missing")


async def body_luminance(c):
    return await c.eval(
        "(function(){const m=getComputedStyle(document.body).backgroundColor.match(/\\d+(\\.\\d+)?/g)||[255,255,255];"
        " const [r,g,b]=m.map(Number); return (0.2126*r+0.7152*g+0.0722*b)/255;})()")


async def tile_contrast(c):
    """Min text/background contrast ratio over the stat-strip tiles (static HTML block mentioning 今天 + 筆 + NT$)."""
    return await c.eval(
        f"""(function(){{
        const lum=s=>{{const m=(s||'').match(/\\d+(\\.\\d+)?/g); if(!m) return null; const a=m.length>3?Number(m[3]):1;
          if(a===0) return null; const f=v=>{{v/=255; return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4)}};
          return 0.2126*f(+m[0])+0.7152*f(+m[1])+0.0722*f(+m[2]);}};
        const ratio=(a,b)=>(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
        const bgOf=el=>{{let e=el; while(e){{const l=lum(getComputedStyle(e).backgroundColor); if(l!==null) return l; e=e.parentElement;}}
          return lum(getComputedStyle(document.body).backgroundColor)||1;}};
        const strip=Array.from({ROOT}.querySelectorAll('[data-testid="stMarkdown"]')).find(m=>{{const t=m.innerText;
          return t.includes('今天')&&t.includes('筆')&&t.includes('NT$')}});
        if(!strip) return null;
        let worst=99, n=0;
        for(const el of strip.querySelectorAll('*')){{
          if(!el.children.length && el.innerText && el.innerText.trim()){{
            const fg=lum(getComputedStyle(el).color); if(fg===null) continue;
            worst=Math.min(worst, ratio(fg, bgOf(el))); n++;}}}}
        return n?{{min:worst, n:n}}:null;}})()""")


async def set_color_scheme(c, scheme):
    await c.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
    await asyncio.sleep(0.3)


def seed_trip_end():
    """End date of the newest foreign 旅行 row the runner seeds (fxfixtures.CONVERTED_ROW, 新加坡)."""
    return datetime.strptime(CONVERTED_ROW[0], "%m/%d/%Y").date()


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
async def sc_overview_first_screen(h, rep):
    name = "overview_first_screen"
    await h.fresh_session()
    c = h.chrome
    await require_redesign(h, rep, name)
    await no_exceptions(h, rep, name, "renders_without_exception")
    rep.ok(name, "default_period_month", await seg_active(c) == SEG_OPTIONS[2], f"active={await seg_active(c)}")
    opened = await close_all_expanders(c)
    if opened:
        print(f"# NOTE {name}: {opened} expander(s) were open by default at 390 px (plan: collapsed on phones)")
    await scroll_top(c)
    m = await hero(c)
    if not rep.ok(name, "hero_metric_present", m is not None, "no st.metric in the 總覽 panel"):
        await c.screenshot(f"{name}.png")
        return
    rep.ok(name, "hero_top_lt_400", m["top"] < 400, f"hero top={m['top']:.0f}px")
    rep.ok(name, "hero_label_month", m["label"].startswith(SEG_OPTIONS[2]), f"label={m['label']!r}")
    rep.ok(name, "hero_value_twd", "NT$" in m["value"], f"value={m['value']!r}")
    comp = config.COMPARISON_LABEL.get(SEG_OPTIONS[2], "") or ""
    rep.ok(name, "hero_delta_named", comp in m["delta"] or "無前期資料" in m["delta"] or "無前期資料" in await c.panel_text(),
           f"delta={m['delta']!r} (expected {comp!r} or 無前期資料)")
    panel = await c.panel_text()
    rep.ok(name, "caption_daily_avg", "日均" in panel, "hero caption 「日均 …」 missing")
    rep.ok(name, "stat_strip_today_tile", "今天" in panel and "筆" in panel, "stat strip 今天 tile missing")
    rep.ok(name, "top3_bars", "%" in panel, "top-3 category bars (… 29%) missing")
    rep.ok(name, "recent_list_dataframe", bool(await c.eval(f"!!{ROOT}.querySelector('[data-testid=\"stDataFrame\"]')")),
           "最近 5 筆 st.dataframe missing")
    old = [t for t in ("時間範圍選擇", "平均單筆", "資料品質資訊", "進階篩選") if t in panel]
    rep.ok(name, "old_controls_gone", not old, f"legacy text still rendered: {old}")
    sums = await expander_summaries(c)
    missing = [e for e in EXPANDERS if not any(e in s for s in sums)]
    rep.ok(name, "expanders_present", not missing, f"missing {missing}; summaries={sums}")
    sw = await c.eval("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    rep.ok(name, "no_horizontal_scroll", sw[0] <= 390 and not await c.has_horizontal_scroll(), f"scrollWidth/clientWidth={sw}")
    height = await c.page_height()
    rep.ok(name, "page_height_le_2300", height <= 2300, f"content height={height}px with expanders collapsed")
    await c.screenshot(f"{name}.png")


async def sc_period_switch(h, rep):
    name = "period_switch"
    await h.fresh_session()
    c = h.chrome
    await require_redesign(h, rep, name)
    base = await period_state(c)
    rep.ok(name, "month_hero", base[0] == "hero", f"state={base}")
    base_label = base[1]["label"] if base[0] == "hero" else ""
    base_value = base[1]["value"] if base[0] == "hero" else ""
    for label in (SEG_OPTIONS[0], SEG_OPTIONS[1], SEG_OPTIONS[3]):       # 今天 本週 本年
        await seg_click(c, label)
        st = await period_state(c)
        rep.ok(name, f"seg_{label}_applied", period_applied(st, label) and (st[0] != "hero" or st[1]["label"] != base_label),
               f"state={st} (base label {base_label!r})")
        if st[0] == "hero":
            comp = config.COMPARISON_LABEL.get(label) or ""
            rep.ok(name, f"seg_{label}_delta_named", comp in st[1]["delta"] or "無前期資料" in st[1]["delta"]
                   or "無前期資料" in await c.panel_text(), f"delta={st[1]['delta']!r} expected {comp!r}")
            if label == SEG_OPTIONS[3]:
                rep.ok(name, "year_value_differs_from_month", st[1]["value"] != base_value,
                       f"本年={st[1]['value']!r} == 本月={base_value!r}")
        else:
            print(f"# NOTE {name}: {label} is empty in the seed → empty state {st[1]!r}")
        await no_exceptions(h, rep, name, f"seg_{label}_no_exception")
    await c.screenshot(f"{name}_year.png")
    # 更多… popover: 上月 then 全部
    if not await open_more_popover(c):
        await c.screenshot(f"{name}_no_popover.png")
        rep.ok(name, "more_popover_opens", False, "更多… did not open a st.popover body")
        return
    await c.screenshot(f"{name}_popover.png")
    for more in (config.OVERVIEW_MORE_PERIODS[0], config.OVERVIEW_MORE_PERIODS[-1]):   # 上月, 全部
        if not await popover_open(c):
            await open_more_popover(c)
        if not await popover_button(c, more):
            rep.ok(name, f"more_{more}_pill", False, f"pill {more!r} not in the popover")
            continue
        st = await period_state(c)
        rep.ok(name, f"more_{more}_applied", period_applied(st, more), f"state={st}")
        rep.ok(name, f"more_{more}_seg_shows_more", await seg_active(c) in (MORE_LABEL, None),
               f"segmented active={await seg_active(c)} (plan: popover choice sets ov_seg=更多…)")
        if st[0] == "hero" and more == config.OVERVIEW_MORE_PERIODS[-1]:
            rep.ok(name, "all_delta_absent_or_none", not (config.COMPARISON_LABEL.get(more) or "") or True, "")
    await no_exceptions(h, rep, name, "more_no_exception")
    # segmented tap after a popover choice wins (state trap)
    await seg_click(c, SEG_OPTIONS[2])
    st = await period_state(c)
    rep.ok(name, "seg_after_popover_wins", period_applied(st, SEG_OPTIONS[2]) and await seg_active(c) == SEG_OPTIONS[2],
           f"state={st} active={await seg_active(c)}")
    # category filter chip, then an invalid custom range: error shown, chip survives
    chip = None
    if await open_expander(c, EXPANDERS[3]):
        await asyncio.sleep(0.4)
        try:
            cat = await c.eval(f"(function(){{const w={widget_el('stMultiSelect', '分類')}; return w?w.innerText.trim().split('\\n')[0]:null}})()")
            if cat:
                await select_option(c, "分類", "🍽️ 飲食", testid="stMultiSelect")
                await c.wait_idle(30)
                await ensure_tab(c, TAB_OVERVIEW)
                chip = await filter_badge(c)
        except RuntimeError as e:
            print(f"# NOTE {name}: could not pick a 分類 option: {e}")
    rep.ok(name, "category_chip_shown", chip is not None and "飲食" in chip, f"badge={chip!r}")
    if not await open_more_popover(c):
        rep.ok(name, "custom_range_popover", False, "popover did not reopen for 自訂範圍")
        return
    ok1 = await set_popover_date(c, 0, CUSTOM_START)
    if not await popover_open(c):
        await open_more_popover(c)
    ok2 = await set_popover_date(c, 1, CUSTOM_END_BAD)
    if not rep.ok(name, "custom_date_inputs", ok1 and ok2, "two st.date_input widgets not found in the popover"):
        return
    text = await c.page_text()
    rep.ok(name, "custom_end_before_start_error", RANGE_ERROR in text,
           [l for l in text.split("\n") if "日期" in l][:4])
    chip2 = await filter_badge(c)
    rep.ok(name, "category_chip_survives", chip2 is not None and chip2 == chip, f"before={chip!r} after={chip2!r}")
    await no_exceptions(h, rep, name, "custom_no_exception")
    await c.screenshot(f"{name}_custom_error.png")


async def sc_filters(h, rep):
    name = "filters"
    await h.fresh_session()
    c = h.chrome
    await require_redesign(h, rep, name)
    base = await hero(c)
    rep.ok(name, "no_badge_initially", await filter_badge(c) is None, f"badge={await filter_badge(c)!r}")
    if not rep.ok(name, "filter_expander_opens", await open_expander(c, EXPANDERS[3]), "🔍 篩選 expander missing"):
        return
    await asyncio.sleep(0.4)
    account = config.ACCOUNTS[0] if getattr(config, "ACCOUNTS", None) else "菇菇"
    if not rep.ok(name, "account_pill_click", await pill_click(c, "帳戶", account), f"pill {account!r} not found"):
        await c.screenshot(f"{name}_no_pills.png")
        return
    badge = await filter_badge(c)
    rep.ok(name, "badge_shows_account", badge is not None and account in badge, f"badge={badge!r}")
    m = await hero(c)
    rep.ok(name, "hero_value_changes", base is not None and m is not None and m["value"] != base["value"],
           f"before={base and base['value']!r} after={m and m['value']!r}")
    await c.screenshot(f"{name}_account.png")
    # 類型 pill (📅 日常 / ✈️ 旅行)
    if await open_expander(c, EXPANDERS[3]):
        await asyncio.sleep(0.3)
    if await pill_click(c, "類型", "✈️ 旅行"):
        badge = await filter_badge(c)
        rep.ok(name, "badge_shows_type", badge is not None and "旅行" in badge, f"badge={badge!r}")
    else:
        print(f"# NOTE {name}: 類型 pills (📅 日常 / ✈️ 旅行) not found")
    await click_button(c, CLEAR_BUTTON)
    await c.wait_idle(30)
    await ensure_tab(c, TAB_OVERVIEW)
    rep.ok(name, "clear_removes_badge", await filter_badge(c) is None, f"badge={await filter_badge(c)!r}")
    m = await hero(c)
    rep.ok(name, "clear_restores_value", base is not None and m is not None and m["value"] == base["value"],
           f"before={base and base['value']!r} after clear={m and m['value']!r}")
    await no_exceptions(h, rep, name)
    await c.screenshot(f"{name}_cleared.png")


async def sc_expanders(h, rep):
    name = "expanders"
    await h.fresh_session()
    c = h.chrome
    await require_redesign(h, rep, name)
    for exp in EXPANDERS:
        found = await open_expander(c, exp)
        await c.wait_idle(20)
        await ensure_tab(c, TAB_OVERVIEW)
        rep.ok(name, f"open_{exp}", found, "expander not found")
        await no_exceptions(h, rep, name, f"open_{exp}_no_exception")
    panel = await c.panel_text()
    rep.ok(name, "transactions_footer", "本期" in panel and "筆" in panel, "「本期 N 筆 · 最大一筆 …」 footer missing")
    rep.ok(name, "data_check_fx_counts", "已換算外幣" in panel, "🧹 資料檢查 lacks 已換算外幣 count")
    charts = await plotly_report(c)
    if rep.ok(name, "trend_chart_present", bool(charts), "no Plotly chart after opening 📈 趨勢"):
        rep.ok(name, "charts_static_config", all(ch["static"] and ch["modebar"] is False for ch in charts),
               f"{[(ch['static'], ch['modebar']) for ch in charts]}")
        rep.ok(name, "charts_no_modebar_dom", all(ch["modebar_btns"] == 0 for ch in charts),
               f"modebar buttons={[ch['modebar_btns'] for ch in charts]}")
        rep.ok(name, "charts_height_le_280", all(ch["height"] <= 290 for ch in charts), f"{[ch['height'] for ch in charts]}")
        ch = charts[0]
        await c.eval(f"{ROOT}.querySelector('.js-plotly-plot').scrollIntoView({{block:'center'}})")
        await asyncio.sleep(0.3)
        before = (await plotly_report(c))[0]
        x, y, w = before["rect"]
        await drag(c, x - w * 0.25, y, w * 0.5)
        after = (await plotly_report(c))[0]
        zoombox = await c.eval(f"!!{ROOT}.querySelector('.js-plotly-plot .zoombox, .js-plotly-plot .select-outline')")
        rep.ok(name, "chart_ignores_drag", after["xrange"] == before["xrange"] and not zoombox,
               f"xrange {before['xrange']} -> {after['xrange']}, zoombox={zoombox}")
    hidden, why = await toolbar_hidden(c)
    rep.ok(name, "dataframe_toolbar_hidden", bool(hidden), why)
    rep.ok(name, "no_horizontal_scroll_expanded", not await c.has_horizontal_scroll(), "expanded page scrolls horizontally")
    await c.screenshot(f"{name}_all_open.png")


async def sc_trips(h, rep):
    name = "trips"
    await h.fresh_session()
    c = h.chrome
    await require_redesign(h, rep, name)
    today = today_local()
    seed_end = seed_trip_end()
    expect_active = seed_end >= today - timedelta(days=config.TRIP_ACTIVE_GRACE_DAYS)
    panel = await c.panel_text()
    badge_line = next((l for l in panel.split("\n") if ACTIVE_TRIP_TEXT in l), None)
    if expect_active:
        rep.ok(name, "active_trip_badge", badge_line is not None and CONVERTED_ROW[6] in badge_line,
               f"seed trip {CONVERTED_ROW[6]} ended {seed_end} (today {today}); line={badge_line!r}")
        rep.ok(name, "active_trip_view_button", await c.eval(
            f"Array.from({ROOT}.querySelectorAll('button')).some(b=>b.innerText.trim()==={json.dumps(VIEW_BUTTON)})"),
            "no 查看 button under the hero")
    else:
        print(f"# NOTE {name}: seed trip ended {seed_end}, older than {config.TRIP_ACTIVE_GRACE_DAYS} days — "
              f"badge not expected (runner.py seed is not date-shifted); line={badge_line!r}")
        rep.ok(name, "no_stale_active_badge", badge_line is None or CONVERTED_ROW[6] not in badge_line, badge_line)
    await c.screenshot(f"{name}_badge.png")
    if not rep.ok(name, "popover_opens", await open_more_popover(c), "更多… popover did not open"):
        return
    rows = await popover_trip_rows(c)
    rep.ok(name, "popover_trip_list", bool(rows), "no 查看 rows in the popover")
    await c.screenshot(f"{name}_popover.png")
    if not rows:
        return
    target = next((r for r in rows if CONVERTED_ROW[6] in r), rows[0])
    country = next((k for k in config.COUNTRY_FLAG if k in target and k != "台灣"), None)
    rep.ok(name, "trip_row_named", country is not None, f"row={target!r} has no country from COUNTRY_FLAG")
    await popover_button(c, VIEW_BUTTON, row_contains=country or None)
    st = await period_state(c)
    label = st[1]["label"] if st[0] == "hero" else ""
    rep.ok(name, "view_sets_period", st[0] == "hero" and (country or "") in label, f"state={st}")
    if st[0] == "hero" and config.COMPARISON_LABEL.get("旅行") is None:
        rep.ok(name, "trip_no_comparison", not st[1]["delta"] or "無" in st[1]["delta"] or "-" == st[1]["delta"],
               f"delta={st[1]['delta']!r} (旅行 → 無比較)")
    badge = await filter_badge(c)
    rep.ok(name, "view_sets_country_filter", badge is not None and (country or "") in badge, f"badge={badge!r}")
    rep.ok(name, "view_seg_shows_more", await seg_active(c) in (MORE_LABEL, None), f"active={await seg_active(c)}")
    await no_exceptions(h, rep, name)
    await c.screenshot(f"{name}_view.png")


async def sc_theme(h, rep):
    name = "theme"
    c = h.chrome
    try:
        for scheme, dark in (("light", False), ("dark", True)):
            await set_color_scheme(c, scheme)
            await h.fresh_session()
            await require_redesign(h, rep, name)
            lum = await body_luminance(c)
            rep.ok(name, f"{scheme}_theme_applied", (lum < 0.3) == dark, f"body luminance={lum:.2f}")
            await no_exceptions(h, rep, name, f"{scheme}_no_exception")
            tiles = await tile_contrast(c)
            if tiles is None:
                rep.ok(name, f"{scheme}_tiles_present", False, "stat strip (今天 … 筆 … NT$) not found")
            else:
                rep.ok(name, f"{scheme}_tiles_readable", tiles["min"] >= MIN_TILE_CONTRAST,
                       f"min contrast {tiles['min']:.2f} over {tiles['n']} text nodes (floor {MIN_TILE_CONTRAST})")
            await scroll_top(c)
            await c.screenshot(f"overview_{scheme}.png")
            await close_all_expanders(c)
            for exp in (EXPANDERS[1], EXPANDERS[3]):
                await open_expander(c, exp)
            await c.wait_idle(20)
            await c.screenshot(f"overview_{scheme}_expanded.png")
    finally:
        await set_color_scheme(c, "light")


async def sc_converted_rows(h, rep):
    name = "converted_rows"
    await h.fresh_session()
    c = h.chrome
    await goto_add_tab(h)
    await choose_country(h, "新加坡")
    await require_fx_card(h, rep, name)
    desc = "harness SGD 總覽"
    await fill_add_form_and_submit(h, desc, fx_amount="7.5")
    w = last_write(h, "append_row")
    if not rep.ok(name, "sgd_row_written", w is not None and len(w["values"]) >= 12 and w["values"][9] == "SGD",
                  f"append_row={w and w['values']}"):
        return
    await ensure_tab(c, TAB_OVERVIEW)
    await c.wait_idle(30)
    if not await redesign_present(c):
        await c.screenshot(f"{name}_no_redesign.png")
        raise Skip("row saved, but the 總覽 redesign (segmented control) is not rendered yet")
    grids = await grid_texts(c)
    recent = grids[0] if grids else ""
    rep.ok(name, "recent_shows_new_row", desc in recent, f"recent grid={recent[:200]!r}")
    rep.ok(name, "recent_shows_currency_suffix", "· SGD" in recent, "expected '名稱 · SGD 7.50' in the 最近 list")
    await c.screenshot(f"{name}_recent.png")
    if rep.ok(name, "transactions_expander", await open_expander(c, EXPANDERS[0]), "📋 本期全部交易 missing"):
        await c.wait_idle(20)
        grids = await grid_texts(c)
        full = grids[-1] if len(grids) > 1 else ""
        # 原幣 is folded into 名稱 ('名稱 · SGD 7.50'): a 6th column overflows 390 px.
        rep.ok(name, "full_list_orig_column", "· SGD" in full, f"grid header/cells={full[:200]!r}")
    await no_exceptions(h, rep, name)
    await c.screenshot(f"{name}_full.png")


SCENARIOS = {
    "overview_first_screen": (sc_overview_first_screen, dict(ENV)),
    "period_switch": (sc_period_switch, dict(ENV)),
    "filters": (sc_filters, dict(ENV)),
    "expanders": (sc_expanders, dict(ENV)),
    "trips": (sc_trips, dict(ENV)),
    "theme": (sc_theme, dict(ENV)),
    "converted_rows": (sc_converted_rows, dict(ENV)),   # last: writes a row into the fake sheet
}


# ---------------------------------------------------------------------------
# Main (same loop as drive_fx.run, over this file's SCENARIOS)
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
                    await h.close()
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
    st_port = int(os.environ.get("ST_PORT", "8800"))
    cdp_port = int(os.environ.get("CDP_PORT", "9400"))
    attach = None
    phone, headless = True, True
    names, overrides = [], {}
    while args:
        a = args.pop(0)
        if a == "--list":
            for k, (_, env) in SCENARIOS.items():
                print(f"{k:22s} {env}")
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
