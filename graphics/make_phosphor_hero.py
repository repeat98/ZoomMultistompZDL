#!/usr/bin/env python3
"""The README hero: the console painting in the screens' phosphor palette.

The source painting (13-ivory-console-film.png) keeps all its detail and
continuous shading; only its colour changes. Luminance, stretched between the
0.5th and 99.7th percentiles and given a gentle curve (^1.25), is mapped onto
the effects overview's ramp: its near-black ground (build/make_thumb_png.py BG),
a deep navy, its pale-blue ink (LIT), and a paler highlight. Only the lit
accents (red LEDs and the like: strongly saturated and bright) keep the
painting's own colour, blended in by how saturated and bright they are.
    python3 graphics/make_shaded_hero.py
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'build'))
from make_thumb_png import BG, LIT  # noqa: E402

SRC, OUT = HERE / '13-ivory-console-film.png', HERE / '15-console-phosphor.jpg'
CURVE = 1.25
RAMP = [(0.0, BG), (0.35, (34, 52, 66)), (0.75, LIT), (1.0, (226, 240, 248))]


def main():
    a = np.asarray(Image.open(SRC).convert('RGB'), float) / 255
    lum = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.7)
    t = np.clip((lum - lo) / (hi - lo), 0, 1) ** CURVE
    xs = [s for s, _ in RAMP]
    cs = np.array([c for _, c in RAMP], float)
    out = np.stack([np.interp(t, xs, cs[:, k]) for k in range(3)], -1)
    sat = a.max(-1) - a.min(-1)
    accent = np.clip((sat - 0.35) * 3, 0, 1) * np.clip((a.max(-1) - 0.45) * 3, 0, 1)
    out = out * (1 - accent[..., None]) + a * 255 * accent[..., None]
    Image.fromarray(np.clip(out, 0, 255).round().astype(np.uint8)).save(OUT, quality=90, optimize=True, progressive=True)
    print(f'-> {OUT}')


if __name__ == '__main__':
    main()
