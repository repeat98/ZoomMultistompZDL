"""Reusable 128x64 Airwindows-style Zoom screen images."""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "build"))

from screen_image import Canvas, encode_zoom_rle  # noqa: E402


def _draw_reel(c: Canvas, cx: int, cy: int, r: int) -> None:
    c.circle(cx, cy, r)
    c.circle(cx, cy, 5)
    c.filled_circle(cx, cy, 2)
    for angle_deg in (90, 210, 330):
        a = math.radians(angle_deg)
        for rr in range(3, r - 1):
            c.px(int(cx + rr * math.cos(a) + 0.5), int(cy - rr * math.sin(a) + 0.5))


def make_airwindows_tape_screen(name: str, number: str = "9") -> bytes:
    """Tape-machine themed Airwindows bitmap, adapted from the old ToTape9 port."""
    c = Canvas()

    c.rect(1, 4, 60, 59)
    _draw_reel(c, 15, 32, 14)
    _draw_reel(c, 47, 32, 14)
    c.hline(29, 29, 22)
    c.hline(33, 33, 22)
    c.rect(29, 19, 33, 27)
    c.hline(30, 32, 23)
    c.vline(63, 2, 61)

    c.draw_text(name[:2].upper(), 66, 4, scale=2, spacing=1)
    c.draw_text(name[2:6].upper(), 66, 18, scale=2, spacing=2)
    if number:
        c.draw_char(number[0], 108, 3, scale=3)

    base_y = 52
    prev_y = None
    for x in range(66, 127):
        t = (x - 66) / 60.0
        raw = math.sin(t * 2.0 * math.pi * 1.5) * 6.0
        clipped = math.copysign(min(abs(raw * 0.9), 5.0), raw)
        y = int(base_y - clipped)
        if prev_y is None:
            c.px(x, y)
        else:
            y0, y1 = (prev_y, y) if prev_y <= y else (y, prev_y)
            c.vline(x, y0, y1)
        prev_y = y

    c.draw_text("AIRWINDOWS", 66, 55, scale=1, spacing=1)
    return encode_zoom_rle(c)
