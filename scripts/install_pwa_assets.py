#!/usr/bin/env python
"""
Make the self-hosted app installable on a phone.

Android will only treat a site as a real app if three things are true:
  1. a web-app manifest is linked from the HTML the server sends,
  2. a service worker with a fetch handler is registered at the site root,
  3. it is served over HTTPS (Cloudflare does that for us).

Streamlit provides none of the first two and its index.html is not editable from
the app. But its own static directory is served at the site ROOT (verified:
/favicon.png), so dropping files there gives us both root-scoped URLs. This
script copies ./static/* next to Streamlit's index.html and adds the manifest
link into that index.html.

Idempotent and self-healing: it is wired into the systemd unit as ExecStartPre,
so a Streamlit upgrade (which replaces index.html) is repaired on the next
restart. Run by hand with:

    expense_env/bin/python scripts/install_pwa_assets.py [--check]
"""
from __future__ import annotations

import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "static")
ASSETS = ("manifest.json", "sw.js", "icon-192.png", "icon-512.png", "icon-maskable-512.png")
MARKER = "<!-- huangliu-expense pwa -->"
HEAD_TAGS = f"""{MARKER}
    <link rel="manifest" href="/manifest.json" />
    <meta name="theme-color" content="#4ECDC4" />
    <meta name="mobile-web-app-capable" content="yes" />
    <link rel="apple-touch-icon" href="/icon-192.png" />
"""


def streamlit_static_dir() -> str:
    import streamlit
    return os.path.join(os.path.dirname(os.path.abspath(streamlit.__file__)), "static")


def patch_index(path: str) -> bool:
    """Add the manifest link to <head>. Returns True when the file was changed."""
    html = open(path, encoding="utf-8").read()
    if MARKER in html:
        return False
    anchor = "</head>"
    if anchor not in html:
        raise SystemExit(f"{path}: no </head> to patch")
    open(path, "w", encoding="utf-8").write(html.replace(anchor, f"    {HEAD_TAGS}  {anchor}", 1))
    return True


def main() -> int:
    check = "--check" in sys.argv
    dst = streamlit_static_dir()
    index = os.path.join(dst, "index.html")
    missing, copied = [], []

    for name in ASSETS:
        src = os.path.join(SRC, name)
        if not os.path.exists(src):
            missing.append(name)
            continue
        target = os.path.join(dst, name)
        same = (os.path.exists(target)
                and os.path.getsize(target) == os.path.getsize(src)
                and open(target, "rb").read() == open(src, "rb").read())
        if same:
            continue
        if not check:
            shutil.copy2(src, target)
        copied.append(name)

    linked = MARKER in open(index, encoding="utf-8").read()
    if missing:
        print("MISSING in ./static:", ", ".join(missing))
    if check:
        print(f"assets needing copy: {copied or 'none'}; index.html linked: {linked}")
        return 0 if not copied and linked and not missing else 1

    if patch_index(index):
        print("patched", index)
    print(f"installed: {', '.join(copied) if copied else 'nothing new'}")
    print("manifest -> /manifest.json, worker -> /sw.js, icons -> /icon-*.png")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
