"""
Login durability scenarios (headless Chrome).

    expense_env/bin/python tests/chrome/drive_auth.py all
    expense_env/bin/python tests/chrome/drive_auth.py cookie_purge

Why this exists: "remember me" can only be written from JavaScript (Streamlit has
no server-side set-cookie API), and a JS-set cookie is the least durable store a
browser offers — WebKit, which every iPhone browser uses, caps it at 7 days and
drops it under storage pressure. So the token is mirrored into localStorage and
restored into the cookie on the next load (auth.restore_auth_cookie_js).

These scenarios reproduce that purge and prove the recovery, and — just as
important — that logout still wins over the backup.

    PASS <scenario> <check>
    FAIL <scenario> <check>: <detail>
    RESULT passed=N failed=N skipped=N
"""
import asyncio
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir))
for p in (HERE, REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from drive_fx import Harness, Report  # noqa: E402

ENV = {"MODE": "api", "FX_HEADERS": "1", "FX_MODE": "live"}
COOKIE = "expense_auth"
PURGE_COOKIE = (f'document.cookie = "{COOKIE}=; Max-Age=0; Path=/";'
                f' document.cookie.indexOf("{COOKIE}=") === -1')
SETTLE = 4.0          # cookie component renders, restore snippet reloads


async def logged_in(c):
    return bool(await c.eval("!!document.querySelector('[data-baseweb=\"tab\"]')"))


async def has_cookie(c):
    return COOKIE + "=" in (await c.eval("document.cookie"))


async def backup(c):
    return await c.eval(f"window.localStorage.getItem({COOKIE!r})")


async def reload(h):
    await h.chrome.navigate(h.url)
    await h.chrome.wait_idle(30)
    await asyncio.sleep(SETTLE)
    await h.chrome.wait_idle(30)


async def sc_cookie_purge(h, rep):
    """A browser that throws the cookie away must not log the family out."""
    name = "cookie_purge"
    await h.open()
    rep.ok(name, "login", await h.login(), "PIN login failed")
    await asyncio.sleep(SETTLE)
    rep.ok(name, "localstorage_backup_written", bool(await backup(h.chrome)),
           "no localStorage copy of the token")

    rep.ok(name, "cookie_purged", bool(await h.chrome.eval(PURGE_COOKIE)), "cookie still set")
    await reload(h)
    rep.ok(name, "still_logged_in", await logged_in(h.chrome),
           "logged out after the cookie was purged — the localStorage restore did not fire")
    rep.ok(name, "cookie_restored", await has_cookie(h.chrome), "cookie not rewritten")


async def sc_logout_wins(h, rep):
    """Logout must clear the backup too, or it would silently log back in."""
    name = "logout_wins"
    await h.open()
    rep.ok(name, "login", await h.login(), "PIN login failed")
    await asyncio.sleep(SETTLE)

    clicked = await h.chrome.eval(
        "(function(){const b=Array.from(document.querySelectorAll('button'))"
        ".find(b=>b.innerText.includes('登出')); if(b) b.click(); return !!b})()")
    rep.ok(name, "logout_button", bool(clicked), "登出 button not found")
    await asyncio.sleep(SETTLE)
    await h.chrome.wait_idle(30)
    rep.ok(name, "login_screen_shown", not await logged_in(h.chrome), "still on the app")
    rep.ok(name, "backup_cleared", not await backup(h.chrome), "localStorage token survived logout")

    await reload(h)
    rep.ok(name, "stays_logged_out", not await logged_in(h.chrome),
           "reload logged the user back in after an explicit logout")


async def sc_reload_stability(h, rep):
    """Ordinary reloads must never bounce to the login screen."""
    name = "reload_stability"
    await h.open()
    rep.ok(name, "login", await h.login(), "PIN login failed")
    await asyncio.sleep(SETTLE)
    logouts = []
    for i in range(6):
        await reload(h)
        if not await logged_in(h.chrome):
            logouts.append(i + 1)
    rep.ok(name, "no_spurious_logout", not logouts, f"logged out on reload(s) {logouts}")


SCENARIOS = {
    "cookie_purge": sc_cookie_purge,
    "logout_wins": sc_logout_wins,
    "reload_stability": sc_reload_stability,
}


async def run(names, h):
    rep = Report()
    try:
        h.start_server(dict(ENV, **getattr(h, "overrides", {})))
        for n in names:
            await SCENARIOS[n](h, rep)
    finally:
        await h.close()
        h.stop_server()
    return rep.summary()


def main(argv):
    st_port, cdp_port, names, overrides = 8802, 9402, [], {}
    phone, headless, attach = True, True, None
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--st-port":
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
    st_port = int(os.environ.get("ST_PORT", st_port))
    cdp_port = int(os.environ.get("CDP_PORT", cdp_port))
    h = Harness(st_port, cdp_port, phone=phone, headless=headless, attach=attach)
    h.overrides = overrides
    return 0 if asyncio.run(run(names, h)) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
