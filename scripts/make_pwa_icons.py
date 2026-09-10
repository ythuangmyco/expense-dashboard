#!/usr/bin/env python
"""
Generate the home-screen icons for the installable app (static/icon-*.png).

Run once; the PNGs are committed. Re-run only to change the look:

    expense_env/bin/python scripts/make_pwa_icons.py

Android needs two sizes plus a "maskable" variant: launchers crop icons to
whatever shape the phone uses (circle, squircle, rounded square), so the maskable
one keeps its artwork inside the middle 80% and lets the background be cut away.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(HERE), "static")
EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
GLYPH = "💰"                       # same mark the app header uses
BG = (78, 205, 196)                # #4ECDC4, the app's accent
FG = (255, 255, 255)


def _emoji(size: int) -> Image.Image | None:
    """💰 rendered from Noto Color Emoji (a bitmap font: fixed 109 px, then scaled)."""
    if not os.path.exists(EMOJI_FONT):
        return None
    try:
        font = ImageFont.truetype(EMOJI_FONT, 109)
        layer = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((80, 80), GLYPH, font=font, anchor="mm", embedded_color=True)
        return layer.crop(layer.getbbox() or (0, 0, 160, 160)).resize((size, size), Image.LANCZOS)
    except Exception:
        return None


def _fallback(size: int) -> Image.Image:
    """A drawn coin, for machines without the emoji font."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=FG)
    d.ellipse((size * 0.12, size * 0.12, size * 0.88, size * 0.88), outline=BG, width=max(2, size // 16))
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", int(size * 0.55))
        d.text((size / 2, size / 2), "$", font=font, fill=BG, anchor="mm")
    except Exception:
        pass
    return img


def icon(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG + (255,))
    if not maskable:                                   # rounded corners for the plain icon
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
        img.putalpha(mask)
    inner = int(size * (0.60 if maskable else 0.70))   # maskable keeps art inside the safe zone
    art = _emoji(inner) or _fallback(inner)
    img.paste(art, ((size - inner) // 2, (size - inner) // 2), art)
    return img


def main() -> None:
    os.makedirs(STATIC, exist_ok=True)
    for size in (192, 512):
        path = os.path.join(STATIC, f"icon-{size}.png")
        icon(size).save(path)
        print("wrote", path)
    path = os.path.join(STATIC, "icon-maskable-512.png")
    icon(512, maskable=True).save(path)
    print("wrote", path)


if __name__ == "__main__":
    main()
