"""Custom 128x64 on-device cover images for the effect pack.

Stock MS-70CDR convention (verified by decoding ~130 stock ZDLs with
build/decode_picture.py): the cover is the FULL 128x64 frame, and the firmware
paints live knob-value boxes (20x15 px, up to 3) ON TOP at the (x,y) in
effectTypeImageInfo. So a good cover is laid out in two bands:

    rows  1..12   effect name (big)
    rows 14..34   effect emblem
    rows 36..62   a knob row: each visible param's label + a dial, positioned
                  to sit exactly under the firmware's value box.

`knob_layout(n)` is the single source of truth for the box/dial x,y — the
linker's default knob_positions and this drawing code both use it, so the
drawn dials line up with the firmware boxes.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "build"))

from screen_image import Canvas, encode_zoom_rle  # noqa: E402

CX, CY = 64, 23          # emblem centre (top band)
KNOB_Y = 46              # firmware value boxes sit at y=46 (rows 46..61)


from lcd_geometry import PIXEL_ASPECT
DEVICE_ASPECT = PIXEL_ASPECT


class _VSquash:
    """Draws onto `canvas` with y pre-compressed by 1/DEVICE_ASPECT around a
    centre `cy`, so round shapes and text appear correct once the LCD stretches
    them vertically. Every primitive routes through the remapped px/hline, so
    circles become wider-than-tall in the bitmap and look round on the device.
    Compress around each element's own centre to preserve layout/alignment."""

    def __init__(self, canvas, cy, aspect=DEVICE_ASPECT):
        self.c = canvas
        self.cy = cy
        self.a = aspect

    def _ry(self, y):
        return int(round(self.cy + (y - self.cy) / self.a))

    def px(self, x, y, v=1):
        self.c.px(x, self._ry(y), v)

    def hline(self, x0, x1, y, v=1):
        self.c.hline(x0, x1, self._ry(y), v)

    def vline(self, x, y0, y1, v=1):
        if y0 > y1:
            y0, y1 = y1, y0
        self.c.vline(x, self._ry(y0), self._ry(y1), v)

    def rect(self, x0, y0, x1, y1, v=1):
        self.hline(x0, x1, y0, v)
        self.hline(x0, x1, y1, v)
        self.vline(x0, y0, y1, v)
        self.vline(x1, y0, y1, v)

    def circle(self, cx, cy, r, v=1):
        x, y, err = r, 0, 0
        while x >= y:
            for dx, dy in [(x, y), (-x, y), (x, -y), (-x, -y),
                           (y, x), (-y, x), (y, -x), (-y, -x)]:
                self.px(cx + dx, cy + dy, v)
            if err <= 0:
                y += 1; err += 2 * y + 1
            if err > 0:
                x -= 1; err -= 2 * x + 1

    def filled_circle(self, cx, cy, r, v=1):
        for dy in range(-r, r + 1):
            w = int((r * r - dy * dy) ** 0.5)
            self.hline(cx - w, cx + w, cy + dy, v)

    def draw_char(self, ch, x0, y0, scale=1, v=1):
        rows = Canvas._FONT.get(ch.upper(), Canvas._FONT[' '])
        for ri, row in enumerate(rows):
            for ci, bit in enumerate(row):
                if bit == '1':
                    for sy in range(scale):
                        for sx in range(scale):
                            self.px(x0 + ci * scale + sx, y0 + ri * scale + sy, v)

    def draw_text(self, text, x0, y0, scale=1, spacing=1, v=1):
        x = x0
        for ch in text:
            self.draw_char(ch, x, y0, scale, v)
            x += 3 * scale + spacing


def knob_layout(n: int):
    """Box positions (knob_id, x, y) for n visible knobs (n = min(3, params)).

    MUST stay in sync with the linker's defaults_by_count so the drawn dials
    line up under the firmware-painted value boxes.
    """
    Y = KNOB_Y
    return {
        0: [],
        1: [(2, 54, Y)],
        2: [(2, 26, Y), (3, 82, Y)],
    }.get(n, [(2, 14, Y), (3, 55, Y), (4, 96, Y)])


def _line(c, x0, y0, x1, y1):
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        c.px(x0, y0)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy; x0 += sx
        if e2 <= dx:
            err += dx; y0 += sy


def _spark(c, x, y, s):
    c.hline(x - s, x + s, y)
    c.vline(x, y - s, y + s)


def _reel(c, cx, cy, r):
    c.circle(cx, cy, r)
    c.filled_circle(cx, cy, 2)
    for ad in (90, 210, 330):
        a = math.radians(ad)
        for rr in range(3, r - 1):
            c.px(int(cx + rr * math.cos(a)), int(cy - rr * math.sin(a)))


# ---- emblems (compact, centred on the top band rows ~14..34) --------------

def _em_shimmer(c):                       # Microloom
    _spark(c, 52, 30, 2); _spark(c, 64, 23, 3); _spark(c, 76, 17, 2)


def _em_flower(c):                        # Flower
    c.filled_circle(CX, CY, 2)
    for k in range(6):
        a = k * math.pi / 3
        c.circle(int(CX + 8 * math.cos(a)), int(CY + 8 * math.sin(a)), 3)


def _em_bars(c):                          # Shatter
    hs = [5, 11, 7, 13, 6, 10, 8]
    for i, h in enumerate(hs):
        c.vline(46 + i * 5, 33 - h, 33)


def _em_dunes(c):                         # Arrakis
    c.circle(82, 15, 3)
    for off, yc in ((0.0, 27), (1.0, 32)):
        prev = None
        for x in range(44, 85):
            t = (x - 44) / 40.0
            y = int(yc - 4 * math.sin(t * 2 * math.pi * 1.5 + off))
            if prev is not None:
                _line(c, x - 1, prev, x, y)
            prev = y


def _em_square(c):                        # Corrupt
    pts = [(46, 32), (46, 16), (60, 16), (60, 32), (74, 32), (74, 16), (84, 16)]
    for i in range(len(pts) - 1):
        _line(c, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])


def _em_rings(c):                         # Klang
    c.circle(57, CY, 7); c.circle(71, CY, 7)
    _line(c, 60, CY - 5, 68, CY + 5); _line(c, 68, CY - 5, 60, CY + 5)


def _em_resonance(c):                     # Howl
    for r in (3, 6, 9):
        c.circle(CX, CY, r)


def _em_bolt(c):                          # Scorch
    pts = [(70, 13), (58, 25), (66, 25), (56, 35)]
    for i in range(len(pts) - 1):
        _line(c, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
        _line(c, pts[i][0] + 1, pts[i][1], pts[i + 1][0] + 1, pts[i + 1][1])


def _em_swirl(c):                         # Lush (chorus)
    for off in (0.0, 1.6):
        prev = None
        for x in range(44, 85):
            t = (x - 44) / 40.0
            y = int(CY - 6 * math.sin(t * 2 * math.pi * 2.0 + off))
            if prev is not None:
                _line(c, x - 1, prev, x, y)
            prev = y


def _em_room(c):                          # Room (reverb)
    c.rect(52, 18, 76, 34)
    _line(c, 52, 18, 60, 13); _line(c, 60, 13, 84, 13)
    _line(c, 84, 13, 84, 29); _line(c, 76, 18, 84, 13)


def _em_stars(c):                         # Galactic (reverb)
    c.circle(CX, CY, 5)
    for k in range(8):
        a = k * math.pi / 4
        c.filled_circle(int(CX + 11 * math.cos(a)), int(CY + 11 * math.sin(a)), 1)
    _spark(c, 46, 15, 2); _spark(c, 84, 33, 2)


def _em_arrows(c):                        # OTT (compressor)
    _line(c, 58, CY - 6, 64, CY - 12); _line(c, 64, CY - 12, 70, CY - 6)
    c.vline(64, CY - 12, CY - 2)
    _line(c, 58, CY + 6, 64, CY + 12); _line(c, 64, CY + 12, 70, CY + 6)
    c.vline(64, CY + 2, CY + 12)


def _em_reel_single(c):                   # Reel — one clean reel
    _reel(c, CX, CY, 10)


def _em_oxide(c):                         # Oxide — reels shedding oxide specks
    _reel(c, 54, 21, 6); _reel(c, 74, 21, 6)
    c.hline(54, 74, 14)
    for x, y in [(48, 30), (58, 33), (64, 30), (72, 33), (80, 31)]:
        c.filled_circle(x, y, 1)


def _em_spool(c):
    # Two reels feeding a head: one continuous, readable tape path.
    for x in (43, 85):
        c.circle(x, 24, 9); c.circle(x, 24, 2)
        for dx, dy in ((0,-8),(0,8),(-8,0),(8,0)):
            _line(c,x,24,x+dx,24+dy)
    _line(c,51,27,58,33);c.hline(58,70,33);_line(c,70,33,77,27)
    c.rect(59,28,69,33)
    for x in (62,65,67):c.vline(x,30,32)


def _em_genloss(c):                       # GenLoss — reels + tangled tape
    _reel(c, 54, 20, 6); _reel(c, 74, 20, 6)
    c.hline(54, 74, 13)
    pts = [(44, 31), (52, 35), (60, 29), (68, 35), (76, 30), (84, 34)]
    for i in range(len(pts) - 1):
        _line(c, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])


def _em_tapehack(c):                      # TapeHack — exploding tape
    _reel(c, CX, CY, 7)
    for k in range(8):
        a = k * math.pi / 4
        _line(c, int(CX + 9 * math.cos(a)), int(CY - 9 * math.sin(a)),
              int(CX + 13 * math.cos(a)), int(CY - 13 * math.sin(a)))


def _em_taffy(c):                         # Taffy — waveform pulled apart
    _line(c, 44, CY, 50, CY - 4); _line(c, 44, CY, 50, CY + 4)   # left arrow
    _line(c, 84, CY, 78, CY - 4); _line(c, 84, CY, 78, CY + 4)   # right arrow
    prev = None
    for x in range(50, 79):
        t = (x - 50) / 28.0
        stretch = 1.0 + 2.5 * t                   # wavelength stretches ->
        y = int(CY - 5 * math.sin(t * 6.28318 * 2.2 / stretch))
        if prev is not None:
            _line(c, x - 1, prev, x, y)
        prev = y


def _em_mangle(c):                        # Mangle — repeats decaying + warping
    # a row of echo "blips" shrinking and jittering as they mutate
    spec = [(44, 0, 8), (56, -3, 6), (68, 4, 4), (80, -2, 3), (90, 2, 2)]
    for cx, dy, h in spec:
        c.vline(cx, CY + dy - h, CY + dy + h)
        c.px(cx - 1, CY + dy - h); c.px(cx + 1, CY + dy - h)
    # a warp squiggle threading through them
    prev = None
    for x in range(44, 92):
        t = (x - 44) / 48.0
        y = int(CY + 9 * math.sin(t * 6.28318 * 1.6) * (1.0 - t))
        if prev is not None:
            _line(c, x - 1, prev, x, y)
        prev = y


def _em_dissolve(c):                      # Dissolve — block eroding to dots
    for y in range(CY - 7, CY + 8):
        c.hline(46, 58, y)
    for x, y, r in [(62, 17, 1), (66, 25, 1), (63, 30, 0), (70, 20, 0),
                    (72, 28, 1), (76, 16, 0), (78, 24, 0), (82, 21, 1),
                    (86, 28, 0), (89, 18, 0)]:
        if r:
            c.filled_circle(x, y, r)
        else:
            c.px(x, y)


def _em_hydra(c):                         # Hydra — one body, a fast head and a slow head
    def wave(x0, x1, ycen, wavelen, amp=3):
        prev = None
        for x in range(x0, x1):
            t = (x - x0) / float(wavelen)
            y = int(ycen - amp * math.sin(t * 6.28318))
            if prev is not None:
                _line(c, x - 1, prev, x, y)
            prev = y
    wave(40, 58, CY, 9)                   # the body: source written to the ring
    wave(62, 92, CY - 5, 7, 2)            # fast head: 2x, wavelength halved, rides high
    wave(62, 92, CY + 6, 24, 3)           # slow head: 0.5x, stretched out, rides low
    _line(c, 58, CY, 62, CY - 5)          # the split into two heads
    _line(c, 58, CY, 62, CY + 6)


def _em_spiral(c):                        # Spiral — echoes climbing a staircase
    # each repeat one step higher and one step shorter: the compounding shift
    base = CY + 8
    for k in range(6):
        x = 42 + k * 9
        top = base - 3 - k * 2
        _line(c, x, top, x, base)          # the repeat
        _line(c, x - 1, base, x + 1, base)  # its foot on the step
    # an arrow head on the last, tallest repeat
    tip = base - 3 - 5 * 2
    _line(c, 42 + 5 * 9, tip, 42 + 5 * 9 - 3, tip + 4)
    _line(c, 42 + 5 * 9, tip, 42 + 5 * 9 + 3, tip + 4)


def _em_stasis(c):
    pts=[(24,26),(29,26),(35,19),(41,29),(46,24)]
    for a,b in zip(pts,pts[1:]):_line(c,*a,*b)
    c.rect(51,16,95,33)
    for x in (54,67,80):
        pts=[(x,28),(x+4,20),(x+9,29),(x+12,24)]
        for a,b in zip(pts,pts[1:]):_line(c,*a,*b)
    c.circle(100,25,5);c.rect(94,20,96,30,0)
    _line(c,102,19,105,21);_line(c,105,21,105,17)


def _em_rooms(c):
    c.rect(32,16,96,33);c.rect(40,20,88,29)
    for a,b in [((32,16),(40,20)),((96,16),(88,20)),((32,33),(40,29)),((96,33),(88,29))]:
        _line(c,*a,*b)
    c.filled_circle(46,25,1)
    # Dotted reflection path, with enough clearance from room edges.
    pts=[(49,25),(67,21),(83,26),(64,29),(49,25)]
    for a,b in zip(pts,pts[1:]):
        steps=max(abs(b[0]-a[0]),abs(b[1]-a[1]))
        for k in range(0,steps+1,3):c.px(round(a[0]+(b[0]-a[0])*k/steps),round(a[1]+(b[1]-a[1])*k/steps))


def _em_dustbox(c):                       # Dustbox — fuzz over a divided sub-octave
    # A square wave drawn as a CONTINUOUS path: horizontal run, vertical
    # transition, horizontal run at the other level. Drawing tops and verticals
    # without the connecting bottoms leaves detached blocks, which is what the
    # first two attempts looked like.
    def square(x0, x1, ycen, half, amp):
        y = ycen - amp
        x = x0
        while x < x1:
            xe = min(x + half, x1)
            c.hline(x, xe, y)
            if xe >= x1:
                break
            ny = ycen + amp if y < ycen else ycen - amp
            c.vline(xe, min(y, ny), max(y, ny))
            y = ny
            x = xe
    # top: the Grunge branch, hard-clipped.
    # Kept clear of the title banner, which is solid down to row 15 -- the first
    # attempt centred this at CY-6 with amp 4, putting its high level at row 13,
    # underneath the banner, so only the verticals and the low runs showed.
    square(38, 90, CY - 3, 6, 3)
    # bottom: the flip-flop octave at a QUARTER of the rate. Two octaves down is
    # the whole point of the circuit, so the emblem shows the ratio.
    square(38, 90, CY + 8, 24, 3)   # rows 28..34, clear of the knob labels


def _em_rewire(c):                        # Rewire — a chain that can be re-ordered
    # Four blocks in series, plus a bracket carrying the signal from the LAST
    # back over to the second. Everything else in this pack is a fixed chain;
    # the re-route is the whole point, so it is what the emblem draws.
    # An earlier attempt crossed the wires between the middle boxes and read as
    # a scribble at 128x64 -- a bracket over the top survives the squash.
    y = CY + 3
    xs = [40, 54, 68, 82]
    for x in xs:
        c.rect(x, y - 4, x + 8, y + 4)
    c.hline(35, 40, y)                     # in
    for x in xs[:-1]:
        c.hline(x + 8, x + 14, y)          # block to block
    c.hline(90, 95, y)                     # out
    # the re-route: up from the last block, back across, down into the second
    top = y - 11
    c.vline(90, top, y - 4)
    c.hline(58, 90, top)
    c.vline(58, top, y - 4)



def _em_gyre(c):                          # Gyre -- a closed loop that spirals inward
    # A ring, drawn as a spiral that does not quite close: the loop is sealed
    # (Feed at 0) yet the pitch keeps winding, so the path circles and steps in.
    # Two turns is enough to read as "spiral" at 128x64; three turns into mud.
    import math
    cx, cy = 64, CY + 6
    prev = None
    steps = 46
    for i in range(steps):
        t = i / (steps - 1.0)
        ang = t * 2.0 * math.pi * 1.85 - math.pi * 0.5
        r = 15.0 - 8.5 * t                 # winding inward
        x = int(round(cx + math.cos(ang) * r * 1.55))   # wider than tall: the
        y = int(round(cy + math.sin(ang) * r * 0.72))   # device pixels are not square
        if prev is not None:
            _line(c, prev[0], prev[1], x, y)
        prev = (x, y)
    # an arrow head on the inner end, pointing along the travel
    if prev is not None:
        _line(c, prev[0], prev[1], prev[0] + 4, prev[1] - 2)
        _line(c, prev[0], prev[1], prev[0] + 3, prev[1] + 3)

EMBLEMS = {
    "Microlm": _em_shimmer, "Flower": _em_flower, "Shatter": _em_bars,
    "Arrakis": _em_dunes, "Corrupt": _em_square, "Klang": _em_rings,
    "GenLoss": _em_genloss, "Howl": _em_resonance, "Scorch": _em_bolt,
    "Reel": _em_reel_single, "Spool": _em_spool, "Oxide": _em_oxide,
    "Lush": _em_swirl, "Room": _em_room,
    "Galactic": _em_stars, "OTT": _em_arrows, "TapeHack": _em_tapehack,
    "Taffy": _em_taffy, "Dissolve": _em_dissolve, "Mangle": _em_mangle,
    "Hydra": _em_hydra, "Spiral": _em_spiral, "Stasis": _em_stasis,
    "Gyre": _em_gyre,
    "Rooms": _em_rooms, "Dustbox": _em_dustbox, "Rewire": _em_rewire,
}


def _draw_knob_row(c, param_names):
    """A label + dial under each firmware value box, aligned to knob_layout."""
    n = min(3, len(param_names))
    for (kid, kx, ky), label in zip(knob_layout(n), param_names[:n]):
        cx = kx + 10                      # box is 20 wide -> centre
        adv = 3 + 1                       # scale-1 glyph advance
        w = len(label) * adv - 1
        lx = max(2, cx - w // 2)
        c.draw_text(label.upper(), lx, 37, scale=1, spacing=1)
        cyd = ky + 7                      # box is 15 tall -> centre
        sq = _VSquash(c, cyd)             # round dial on device
        sq.circle(cx, cyd, 6)
        sq.vline(cx, cyd - 5, cyd)        # pointer


COVERS_DIR = Path(__file__).resolve().parent / "covers"


def _load_override(name: str):
    """If covers/<Name>.json exists (hand-drawn in tools/cover_editor.html),
    use that exact bitmap instead of the generated cover. A malformed file
    warns and falls back to the generated cover rather than killing the build."""
    f = COVERS_DIR / f"{name}.json"
    if not f.exists():
        return None
    import json
    try:
        rows = json.loads(f.read_text())["grid"]
        c = Canvas()
        for y in range(min(64, len(rows))):
            row = rows[y]
            for x in range(min(128, len(row))):
                if row[x]:
                    c.px(x, y)
        return encode_zoom_rle(c)
    except Exception as exc:  # noqa: BLE001 — any bad override falls back
        print(f"[covers] WARNING: override {f.name} unusable ({exc}); "
              f"using generated cover")
        return None


def make_cover(name: str, param_names=None) -> bytes:
    if name in {"Stasis", "Spool", "Rooms"}:
        from stock_style_covers import draw
        return encode_zoom_rle(draw(name, (param_names or [])[:3]))
    from pack_covers import NAMES, draw as draw_pack
    if name in NAMES:
        return encode_zoom_rle(draw_pack(name, param_names or []))
    override = _load_override(name)
    if override is not None:
        return override
    c = Canvas()
    c.rect(1, 1, 126, 62)
    # Inverse-video name banner: solid bar with the name knocked out, like
    # stock covers. Bold fills are what make the tiny Effect Manager
    # thumbnail (which renders this same picture) read as real art instead
    # of a washed-out generic pedal.
    for by in range(2, 16):
        c.hline(2, 125, by)
    adv = 3 * 2 + 1                       # scale-2 glyph advance
    w = len(name) * adv - 1
    x = max(3, (128 - w) // 2)
    _VSquash(c, 9, aspect=1 if name in {"Stasis", "Spool", "Rooms"} else DEVICE_ASPECT).draw_text(name.upper(), x, 4, scale=2, spacing=1, v=0)
    fn = EMBLEMS.get(name)
    if fn:
        fn(_VSquash(c, CY))              # emblem drawn round-on-device
    if param_names:
        _draw_knob_row(c, param_names)
    return encode_zoom_rle(c)
