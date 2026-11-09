#!/usr/bin/env python3
"""Render graphics/thumb_editors.png -- the editor hero -- from current editor screenshots.

Composition follows the June 2026 hero: an eyebrow, a big title, and the two
editors side by side. What is different is that the June one was an ILLUSTRATION
of the editors drawn by hand, and a drawing cannot go out of date loudly -- it
just quietly stops matching the thing it depicts, exactly as the effects hero sat
at "x16" long after the pack passed sixteen.

Both panels here are real Playwright screenshots of the real pages in their own
P4 "television white blend" theme. The patch on screen is injected the way the
pedal sends one -- a synthetic 146-byte 0x28 dump handed to the page's own
handleSysex() -- so slots, knob counts and cover previews come from the editor's
real code paths. When Rewire's Shift knob was missing from the editor's effect DB,
this image showed seven knobs, which is how the staleness got caught.

The current Arrakis bitmap is imported through the JSON file input, so the
capture does not depend on the cover editor's older embedded examples.

Both pages are shown as they open, in their default LCD theme (2026-10-19:
the editors moved from the dark P4 phosphor look to it, and the old hero,
cropped to the slot cards in P4, no longer looked like either page). The patch
side shows the header and toolbar (DSP meter, Library, Settings) above the
slots.

Usage:
    python3 build/make_editor_thumb.py        # needs a server on PORT
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

from make_thumb_png import draw_text  # noqa: E402

# The pages' default "LCD" theme (patch_editor.html :root): pale blue ground,
# dark ink, 3px borders with an offset shadow.
BG = (0xA6, 0xD2, 0xF0)      # --lcd
INK = (0x0B, 0x1A, 0x27)     # --ink
SOFT = (0x34, 0x56, 0x6B)    # --ink-soft

from PIL import Image  # noqa: E402

PORT = int(__import__("os").environ.get("PORT", 8766))
PATCH_URL = f"http://127.0.0.1:{PORT}/tools/patch_editor.html"
COVER_URL = f"http://127.0.0.1:{PORT}/tools/cover_editor.html"
OUT = ROOT / "graphics" / "thumb_editors.png"

CANVAS = (1600, 900)
PANEL = (700, 600)          # each editor panel
PANEL_Y = 250
MARGIN = 70
GAP = CANVAS[0] - 2 * MARGIN - 2 * PANEL[0]

# Slot 4 is deliberately OFF: the bypass state is part of what the editor looks
# like, and a frame where every slot is lit does not show it.
SLOTS = [
    (1, 1075970832),   # Rewire
    (1, 7340816),      # Stasis
    (1, 1075708688),   # Dustbox
    (0, 1073873680),   # Spiral  (off)
    (1, 3146512),      # Galactic
    (1, 2491152),      # Oxide
]

COMMON_JS = """
  // The pages as they open: default LCD theme. The fixed status bar at the
  // bottom would cut across the slots, and file pickers render as OS widgets.
  const nb = document.getElementById('noticeBar'); if (nb) nb.style.display = 'none';
  document.querySelectorAll('input[type=file]').forEach(e => e.style.visibility = 'hidden');
"""

PATCH_JS = """
() => {
  __COMMON__
  const base = new Uint8Array(146);
  base[0]=0xF0; base[1]=0x52; base[2]=0x00; base[3]=0x61; base[4]=0x28; base[145]=0xF7;
  const p = decodePatch(base);
  const slots = __SLOTS__;
  for (let i = 0; i < 6; i++) {
    const [on, id] = slots[i];
    p.fx[i] = [on, id, ...BYID[id].params.map(p => p.default), 0, 0, 0].slice(0, 11);
  }
  p.name = 'FARLOW RUD';
  p.curfx = 0; p.maxfx = 6;
  handleSysex(encodePatch(p, base));
  document.querySelectorAll('#patpanel, #libpanel').forEach(d => d.classList.add('collapsed'));
  return true;
}
"""

COVER_JS = """
() => {
  __COMMON__
  // Load a cover through the page's own dropdown + Load button rather than
  // poking its grid: an empty canvas is not what the cover editor looks like in
  // use, and driving the real path means a broken loader would show up here.
  const sel = document.getElementById('loadSel');
  const btn = document.getElementById('loadBtn');
  if (sel && btn) {
    const opt = [...sel.options].find(o => /arrakis/i.test(o.textContent + o.value));
    if (opt) { sel.value = opt.value; sel.dispatchEvent(new Event('change', {bubbles:true})); btn.click(); }
  }
  return true;
}
"""


def shoot(url, js, vw, vh, selector, out_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=2)
        page.goto(url, wait_until="networkidle")
        page.evaluate(js)
        if url == COVER_URL:
            import json
            from decode_picture import decode_picture
            rows, _ = decode_picture(str(ROOT / "dist" / "Arrakis.ZDL"))
            page.locator('#jsonIn').set_input_files({"name": "Arrakis.json", "mimeType": "application/json", "buffer": json.dumps({"grid": rows}).encode()})
        page.wait_for_timeout(700)
        target = page.query_selector(selector) if selector else None
        (target or page).screenshot(path=str(out_path))
        b.close()


def fit(img: Image.Image, box) -> Image.Image:
    """Cover-fit into the panel box, anchored top-left, then hard-crop."""
    bw, bh = box
    scale = max(bw / img.width, bh / img.height)
    # Never upscale a capture past 1:1 of its own device pixels -- it goes soft,
    # and soft under a tape pass just reads as out of focus.
    scale = min(scale, 1.0)
    nw, nh = max(bw, int(img.width * scale)), max(bh, int(img.height * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    return img.crop((0, 0, bw, bh))


def label(canvas: Image.Image):
    """Eyebrow + title, in the same cover font the effects hero uses."""
    g = np.zeros((110, 1400), dtype=bool)
    draw_text(g, "ZOOM MS-70CDR / WEB MIDI", 0, 4, scale=3, spacing=3)
    draw_text(g, "PATCH + COVER EDITOR", 0, 34, scale=9, spacing=7)
    px = canvas.load()
    ys, xs = np.nonzero(g)
    for y, x in zip(ys, xs):
        cy, cx = PANEL_Y - 150 + int(y), MARGIN + int(x)
        if 0 <= cy < canvas.height and 0 <= cx < canvas.width:
            px[cx, cy] = INK if y > 28 else SOFT


def frame(canvas: Image.Image, img: Image.Image, x: int, y: int, title: str):
    """Paste a panel the way the pages draw theirs: a 3px ink border and a solid
    offset shadow, with a caption above."""
    from PIL import ImageDraw
    d = ImageDraw.Draw(canvas)
    w, h = img.size
    d.rectangle([x + 6 - 3, y + 6 - 3, x + w + 6 + 2, y + h + 6 + 2], fill=INK)      # shadow
    d.rectangle([x - 3, y - 3, x + w + 2, y + h + 2], fill=INK)                     # border
    canvas.paste(img, (x, y))
    g = np.zeros((30, 700), dtype=bool)
    draw_text(g, title, 0, 0, scale=4, spacing=4)
    px = canvas.load()
    ys, xs = np.nonzero(g)
    for gy, gx in zip(ys, xs):
        cy, cx = y - 38 + int(gy), x + int(gx)
        if 0 <= cy < canvas.height and 0 <= cx < canvas.width:
            px[cx, cy] = INK


def main() -> int:
    import urllib.request
    try:
        urllib.request.urlopen(PATCH_URL, timeout=3)
    except Exception:
        print(f"no server on {PORT}. From the repo root:\n"
              f"    python3 -m http.server {PORT} --bind 127.0.0.1", file=sys.stderr)
        return 1

    tmp = ROOT / "graphics"
    a, b = tmp / "_p.png", tmp / "_c.png"
    shoot(PATCH_URL,
          PATCH_JS.replace("__COMMON__", COMMON_JS)
                  .replace("__SLOTS__", str([list(s) for s in SLOTS])),
          1000, int(1000 * PANEL[1] / PANEL[0]), None, a)
    # Wider viewport than the patch side: the cover editor's 128x64 canvas is drawn
    # at a large zoom, and at 760 CSS px the right-hand knob label falls off the edge.
    # The aspect is matched to PANEL so the scale-down lands exactly, no crop.
    shoot(COVER_URL, COVER_JS.replace("__COMMON__", COMMON_JS),
          1100, int(1100 * PANEL[1] / PANEL[0]), None, b)

    canvas = Image.new("RGB", CANVAS, BG)
    label(canvas)
    frame(canvas, fit(Image.open(a).convert("RGB"), PANEL), MARGIN, PANEL_Y, "PATCH EDITOR")
    frame(canvas, fit(Image.open(b).convert("RGB"), PANEL),
          MARGIN + PANEL[0] + GAP, PANEL_Y, "COVER EDITOR")

    canvas.save(OUT)
    a.unlink(missing_ok=True)
    b.unlink(missing_ok=True)
    print(f"  {OUT.relative_to(ROOT)}  ({CANVAS[0]}x{CANVAS[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
