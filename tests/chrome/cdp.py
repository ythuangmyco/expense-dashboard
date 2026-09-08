"""
Minimal Chrome DevTools Protocol driver for headless Chrome (tornado websockets,
which Streamlit already depends on — no extra packages).

    c = Chrome(port=9350)                # CDP port
    await c.start(url)                   # launches Chrome, emulates a 390x844 phone
    await c.wait_idle()                  # Streamlit finished its rerun
    await select_option(c, "國家", "新加坡")
    await c.screenshot("add_tab.png")    # saved under tests/chrome/out/
    await c.stop()

Phone emulation (PLAN §5: "Headless Chrome 390 px … touch emulation"):
    Emulation.setDeviceMetricsOverride 390x844 @2x mobile=True
    Emulation.setTouchEmulationEnabled  maxTouchPoints=5
    iPhone user agent
Set ``Chrome(phone=False)`` for the old 1400x2400 desktop window.
"""
import asyncio
import base64
import json
import os
import subprocess
import time
import urllib.request

from tornado.websocket import websocket_connect

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("HARNESS_OUT") or os.path.join(HERE, "out")
CHROME = os.environ.get("CHROME_BIN") or next(
    (p for p in ("/opt/google/chrome/chrome", "/usr/bin/google-chrome",
                 "/usr/bin/chromium", "/usr/bin/chromium-browser") if os.path.exists(p)),
    "google-chrome")

PHONE = {"width": 390, "height": 844, "deviceScaleFactor": 2, "mobile": True}
PHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


class Chrome:
    def __init__(self, port=9350, phone=True, headless=True):
        self.port = port
        self.phone = phone
        self.headless = headless
        self.proc = None
        self.ws = None
        self.msg_id = 0
        self.pending = {}
        self.events = []
        self.reader_task = None
        os.makedirs(OUT_DIR, exist_ok=True)

    # -- lifecycle ---------------------------------------------------------
    async def start(self, url):
        udd = os.path.join(OUT_DIR, f"chrome_udd_{self.port}")
        size = "390,844" if self.phone else "1400,2400"
        args = [CHROME, "--no-sandbox", "--disable-gpu", "--no-first-run",
                "--disable-dev-shm-usage", "--disable-background-networking",
                f"--remote-debugging-port={self.port}", f"--user-data-dir={udd}",
                f"--window-size={size}", "about:blank"]
        if self.headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(
            args, stdout=subprocess.DEVNULL,
            stderr=open(os.path.join(OUT_DIR, f"chrome_{self.port}.log"), "ab"))
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://localhost:{self.port}/json"))
                page = [t for t in tabs if t["type"] == "page"][0]
                break
            except Exception:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("chrome did not start")
        self.ws = await websocket_connect(page["webSocketDebuggerUrl"], max_message_size=200 * 1024 * 1024)
        self.reader_task = asyncio.ensure_future(self._reader())
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Log.enable")
        await self.send("Network.enable")
        if self.phone:
            await self.send("Emulation.setDeviceMetricsOverride", **PHONE)
            await self.send("Emulation.setTouchEmulationEnabled", enabled=True, maxTouchPoints=5)
            await self.send("Emulation.setUserAgentOverride", userAgent=PHONE_UA, platform="iPhone")
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(1)

    async def navigate(self, url):
        await self.send("Page.navigate", url=url)
        await asyncio.sleep(1)

    async def stop(self):
        try:
            await self.send("Browser.close")
        except Exception:
            pass
        if self.reader_task:
            self.reader_task.cancel()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except Exception:
                self.proc.kill()

    # -- protocol ----------------------------------------------------------
    async def _reader(self):
        while True:
            raw = await self.ws.read_message()
            if raw is None:
                break
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self.pending:
                self.pending.pop(msg["id"]).set_result(msg)
            else:
                self.events.append(msg)

    async def send(self, method, **params):
        self.msg_id += 1
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.msg_id] = fut
        await self.ws.write_message(json.dumps({"id": self.msg_id, "method": method, "params": params}))
        return await asyncio.wait_for(fut, 30)

    async def eval(self, expr, await_promise=False):
        r = await self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=await_promise)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            raise RuntimeError(json.dumps(res["exceptionDetails"])[:500])
        return res.get("result", {}).get("value")

    # -- streamlit-aware waits -------------------------------------------
    async def wait_idle(self, timeout=15):
        """Wait until Streamlit reports not running (status widget gone, twice in a row)."""
        t0 = time.time()
        await asyncio.sleep(0.5)
        while time.time() - t0 < timeout:
            running = await self.eval("!!document.querySelector('[data-testid=\"stStatusWidget\"]')")
            if not running:
                await asyncio.sleep(0.4)
                running = await self.eval("!!document.querySelector('[data-testid=\"stStatusWidget\"]')")
                if not running:
                    return True
            await asyncio.sleep(0.3)
        return False

    async def wait_for(self, js_bool_expr, timeout=15, step=0.25):
        """Poll a JS expression until truthy; returns the value or None on timeout."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = await self.eval(js_bool_expr)
            if v:
                return v
            await asyncio.sleep(step)
        return None

    # -- input ---------------------------------------------------------------
    async def rect(self, js_el):
        return await self.eval(
            f"(function(){{const el={js_el}; if(!el) return null; el.scrollIntoView({{block:'center'}});"
            " const r=el.getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2];})()")

    async def click(self, js_el):
        """Mouse click at the element centre (works under touch emulation too)."""
        pt = await self.rect(js_el)
        if pt is None:
            raise RuntimeError(f"element not found: {js_el}")
        x, y = pt
        await self.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.send("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await self.send("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left", clickCount=1)
        await asyncio.sleep(0.3)

    async def tap(self, js_el):
        """Touch tap (touchStart/touchEnd) at the element centre."""
        pt = await self.rect(js_el)
        if pt is None:
            raise RuntimeError(f"element not found: {js_el}")
        x, y = pt
        await self.send("Input.dispatchTouchEvent", type="touchStart", touchPoints=[{"x": x, "y": y}])
        await self.send("Input.dispatchTouchEvent", type="touchEnd", touchPoints=[])
        await asyncio.sleep(0.3)

    async def type_text(self, text):
        await self.send("Input.insertText", text=text)
        await asyncio.sleep(0.2)

    async def key(self, key, code=None, keyCode=None):
        p = dict(key=key)
        if code:
            p["code"] = code
        if keyCode:
            p["windowsVirtualKeyCode"] = keyCode
            p["nativeVirtualKeyCode"] = keyCode
        await self.send("Input.dispatchKeyEvent", type="keyDown", **p)
        await self.send("Input.dispatchKeyEvent", type="keyUp", **p)
        await asyncio.sleep(0.2)

    async def blur(self):
        """Tap a neutral spot (page title) so an st.number_input commits its value."""
        await self.eval("(function(){const a=document.activeElement; if(a&&a.blur) a.blur();})()")
        await asyncio.sleep(0.2)
        try:
            await self.click("document.querySelector('h1, [data-testid=\"stHeading\"]') || document.body")
        except RuntimeError:
            pass

    # -- inspection ----------------------------------------------------------
    async def content_height(self):
        """Height of the scrolled content. Streamlit scrolls inside its main section, not the document."""
        return await self.eval(
            "Math.max(document.documentElement.scrollHeight, ...Array.from(document.querySelectorAll("
            "'section.main, [data-testid=\"stMain\"], [data-testid=\"stAppViewContainer\"], "
            "[data-testid=\"stMainBlockContainer\"]')).map(e=>e.scrollHeight))")

    async def screenshot(self, name, full_page=True):
        """PNG under tests/chrome/out/. full_page temporarily grows the emulated viewport to the content height."""
        params = dict(format="png", captureBeyondViewport=True)
        restore = False
        if full_page and self.phone:
            h = int(await self.content_height() or 0)
            if h > PHONE["height"]:
                await self.send("Emulation.setDeviceMetricsOverride", **{**PHONE, "height": min(h, 12000)})
                await asyncio.sleep(0.4)
                restore = True
        r = await self.send("Page.captureScreenshot", **params)
        if restore:
            await self.send("Emulation.setDeviceMetricsOverride", **PHONE)
            await asyncio.sleep(0.2)
        path = name if os.path.isabs(name) else os.path.join(OUT_DIR, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        return path

    async def page_text(self):
        return await self.eval("document.body.innerText")

    async def panel_text(self):
        """innerText of the visible tab panel (falls back to the whole body)."""
        return await self.eval(
            "(function(){const p=document.querySelector('[data-baseweb=\"tab-panel\"]:not([hidden])');"
            " return p?p.innerText:document.body.innerText})()")

    async def exceptions(self):
        return await self.eval(
            "Array.from(document.querySelectorAll('[data-testid=\"stException\"]')).map(e=>e.innerText)")

    async def alerts(self):
        return await self.eval(
            "Array.from(document.querySelectorAll('[data-testid=\"stAlert\"], [data-testid=\"stAlertContainer\"]'))"
            ".map(e=>e.innerText)")

    async def metrics(self):
        """[(label, value)] of every st.metric in the visible tab panel."""
        return await self.eval(
            f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stMetric\"]')).map(m=>["
            "(m.querySelector('[data-testid=\"stMetricLabel\"]')||{}).innerText||'',"
            "(m.querySelector('[data-testid=\"stMetricValue\"]')||{}).innerText||''])")

    async def has_horizontal_scroll(self):
        return await self.eval("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")

    async def page_height(self):
        return await self.content_height()

    def console_errors(self):
        out = []
        for e in self.events:
            if e.get("method") == "Runtime.exceptionThrown":
                out.append(("exception", json.dumps(e["params"]["exceptionDetails"])[:300]))
            elif e.get("method") == "Log.entryAdded" and e["params"]["entry"]["level"] == "error":
                out.append(("log", e["params"]["entry"]["text"][:300]))
            elif e.get("method") == "Runtime.consoleAPICalled" and e["params"]["type"] == "error":
                out.append(("console", " ".join(
                    str(a.get("value", a.get("description", ""))) for a in e["params"]["args"])[:300]))
        return out


# ---------------------------------------------------------------------------
# Helpers for Streamlit widgets (label text -> DOM element)
#
# Streamlit keeps the inactive tab panels in the DOM (hidden). Every lookup
# below is scoped to ROOT = the visible tab panel (or the document when no
# tabs are rendered, e.g. the login screen) so the 新增 tab's widgets are never
# mistaken for the 編輯 tab's.
# ---------------------------------------------------------------------------
ROOT = "(document.querySelector('[data-baseweb=\"tab-panel\"]:not([hidden])')||document)"


def label_el(label):
    """JS expression returning the widget label element whose text starts with `label`."""
    return (f"Array.from({ROOT}.querySelectorAll('[data-testid=\"stWidgetLabel\"]'))"
            f".find(e=>e.innerText.trim().startsWith({json.dumps(label)}))")


def widget_el(testid, label, nth=0):
    """JS expression: the nth `[data-testid=testid]` container (in the visible panel) whose text starts with `label`."""
    return (f"(function(){{const ls=Array.from({ROOT}.querySelectorAll('[data-testid={json.dumps(testid)}]'))"
            f".filter(s=>s.innerText.trim().startsWith({json.dumps(label)})); return ls[{nth}]||null;}})()")


async def widget_present(c, testid, label):
    return bool(await c.eval(f"!!({widget_el(testid, label)})"))


async def selectbox_value(c, label, nth=0):
    return await c.eval(
        f"(function(){{const s={widget_el('stSelectbox', label, nth)}; if(!s) return null;"
        " const v=s.querySelector('[data-baseweb=\"select\"]'); return v?v.innerText.trim():null})()")


async def select_option(c, label, option, nth=0, testid="stSelectbox"):
    """Open a BaseWeb selectbox by label and click the option whose text equals `option`."""
    container = widget_el(testid, label, nth)
    if not await c.eval(f"!!({container})"):
        raise RuntimeError(f"selectbox {label!r} not found")
    if await c.eval("!!document.querySelector('ul[role=\"listbox\"]')"):
        await c.key("Escape")
        await asyncio.sleep(0.3)
    for attempt in range(4):
        await c.click(container + ".querySelector('[data-baseweb=\"select\"]')")
        for _ in range(20):
            if await c.eval("!!document.querySelector('li[role=\"option\"]')"):
                break
            await asyncio.sleep(0.15)
        if await c.eval("!!document.querySelector('li[role=\"option\"]')"):
            break
        await c.key("Escape")
        await asyncio.sleep(0.5)
    await asyncio.sleep(0.2)
    opt = ("Array.from(document.querySelectorAll('li[role=\"option\"]'))"
           f".find(e=>e.innerText.trim()==={json.dumps(option)})")
    found = await c.eval(f"!!({opt})")
    if not found:
        # scroll the listbox looking for it (BaseWeb virtualises long lists)
        for _ in range(10):
            await c.eval("(function(){const l=document.querySelector('ul[role=\"listbox\"]'); if(l) l.scrollTop+=200;})()")
            await asyncio.sleep(0.15)
            if await c.eval(f"!!({opt})"):
                found = True
                break
    if not found:
        opts = await c.eval("Array.from(document.querySelectorAll('li[role=\"option\"]')).map(e=>e.innerText.trim())")
        await c.key("Escape")
        raise RuntimeError(f"option {option!r} not in {opts}")
    await c.click(opt)
    for _ in range(20):
        if not await c.eval("!!document.querySelector('ul[role=\"listbox\"]')"):
            break
        await asyncio.sleep(0.15)
    else:
        await c.key("Escape")
    await asyncio.sleep(0.3)


async def select_option_containing(c, label, substring, nth=0):
    """Like select_option but picks the first option whose text contains `substring`."""
    container = widget_el("stSelectbox", label, nth)
    await c.click(container + ".querySelector('[data-baseweb=\"select\"]')")
    await c.wait_for("!!document.querySelector('li[role=\"option\"]')", timeout=5)
    opt = ("Array.from(document.querySelectorAll('li[role=\"option\"]'))"
           f".find(e=>e.innerText.includes({json.dumps(substring)}))")
    if not await c.eval(f"!!({opt})"):
        opts = await c.eval("Array.from(document.querySelectorAll('li[role=\"option\"]')).map(e=>e.innerText.trim())")
        await c.key("Escape")
        raise RuntimeError(f"no option containing {substring!r} in {opts}")
    await c.click(opt)
    await asyncio.sleep(0.3)


async def fill_input(c, label, text, testid="stNumberInput", clear=True, nth=0):
    """Focus the <input> of a labelled widget, replace its content, type `text`."""
    inp = f"({widget_el(testid, label, nth)}).querySelector('input, textarea')"
    if not await c.eval(f"!!({inp})"):
        raise RuntimeError(f"input {label!r} ({testid}) not found")
    await c.click(inp)
    if clear:
        await c.eval(f"(function(){{const i={inp}; i.select();}})()")
        await c.key("Backspace", "Backspace", 8)
    await c.type_text(text)


async def input_value(c, label, testid="stNumberInput", nth=0):
    return await c.eval(f"(function(){{const w={widget_el(testid, label, nth)}; if(!w) return null;"
                        " const i=w.querySelector('input, textarea'); return i?i.value:null})()")


async def set_checkbox(c, label, on=True):
    js = widget_el("stCheckbox", label)
    if not await c.eval(f"!!({js})"):
        raise RuntimeError(f"checkbox {label!r} not found")
    checked = await c.eval(f"({js}).querySelector('input').checked")
    if bool(checked) != on:
        await c.click(js + ".querySelector('label')")


async def click_button(c, text, nth=0):
    js = (f"(function(){{const bs=Array.from(document.querySelectorAll('button'))"
          f".filter(b=>b.innerText.trim()==={json.dumps(text)}); return bs[{nth}]||null;}})()")
    await c.click(js)


async def click_tab(c, text):
    js = (f"Array.from(document.querySelectorAll('[data-baseweb=\"tab\"]'))"
          f".find(b=>b.innerText.trim()==={json.dumps(text)})")
    await c.click(js)


async def active_tab(c):
    return await c.eval(
        "(function(){const t=Array.from(document.querySelectorAll('[data-baseweb=\"tab\"]'))"
        ".find(x=>x.getAttribute('aria-selected')==='true'); return t?t.innerText.trim():null})()")


async def ensure_tab(c, name, timeout=20):
    if await active_tab(c) != name:
        await click_tab(c, name)
        await c.wait_idle(timeout)


async def open_expander(c, text):
    """Click the expander whose summary contains `text`; returns True when found."""
    return await c.eval(
        f"(function(){{const e=Array.from({ROOT}.querySelectorAll('summary'))"
        f".find(s=>s.innerText.includes({json.dumps(text)})); if(e && !e.parentElement.open) e.click(); return !!e;}})()")
