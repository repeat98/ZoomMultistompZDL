#!/usr/bin/env python3
"""Render dist/*.ZDL on-device covers to the graphics/ gallery PNGs.

The gallery images had no generator -- they were made by hand in June 2026 and
then went stale the moment any effect's knobs were renamed. Hydra's still read
WINDOW / FAST / SLOW long after those knobs became Div / Tempo / Fast.

Geometry and palette are matched to the existing files rather than invented.
Output is not byte-identical to the June set: those were rendered from an older
cover whose border bled to the frame edge, while make_cover now draws it inset
by a pixel. The framing is the same; the art is simply current.

The cover is decoded from the ZDL, then scaled with nearest-neighbor pixels.
The physical pixel aspect comes from lcd_geometry.PIXEL_ASPECT (about 1.4),
so a 128x64 bitmap is displayed at approximately 10:7, matching PE. No VHS
filter is applied to the release gallery.

Which effects, and where each picture comes from (cover, live screen or a
loader example), is listed in readme_art.py.

Usage:
    python3 build/make_gallery_png.py            # every README entry
    python3 build/make_gallery_png.py Stasis     # just one
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

from decode_picture import decode_picture  # noqa: E402
from make_thumb_png import vhs  # noqa: E402

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow is required: pip install pillow")

# P4 "television white blend" -- the editor's TV phosphor theme, so the gallery,
# the hero and the editor all look like the same machine. The June palette was the
# light-blue LCD skin and clashed the moment the hero went to tape.
BG = (8, 9, 11)
LIT = (157, 193, 216)
from lcd_geometry import PIXEL_ASPECT
INNER = (630, round(630 * 64 / 128 * PIXEL_ASPECT))
CANVAS = (640, INNER[1] + 12)
ORIGIN = (5, 6)


def render(name: str, out: Path) -> None:
    import readme_art
    cover = readme_art.to_image(readme_art.bits_for(name), INNER, BG, LIT)
    canvas = Image.new("RGB", CANVAS, BG)
    canvas.paste(cover, ORIGIN)
    # Native artwork: no texture that obscures pixels at pedal size.
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)


def main() -> int:
    import readme_art as A
    every = A.PACK + A.EXPERIMENTAL + A.MATUJUICE + [e[0] for e in A.EXAMPLES]
    wanted = sys.argv[1:]
    if wanted:
        keep = {w.lower() for w in wanted}
        names = [n for n in every if n.lower() in keep]
        if not names:
            print(f"no README entry named {wanted}", file=sys.stderr)
            return 1
    else:
        names = every
    for n in names:
        out = ROOT / "graphics" / f"{n.lower()}.png"
        render(n, out)
        print(f"  {n:<12} -> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
