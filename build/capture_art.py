"""Generic capture covers, drawn at the pedal's native resolution."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/airwindows/common'))
from screen_image import Canvas, encode_zoom_rle
from stock_style_covers import fill, line, round_shape, FONT
from pack_covers import word

def draw(kind):
    c = Canvas()
    c.rect(2, 1, 125, 63)
    fill(c, 5, 3, 122, 33)
    if kind == 'NAM':
        # Neural lattice: three columns of physically round nodes.
        nodes = [[(14, 12), (14, 25)], [(28, 8), (28, 18), (28, 28)], [(42, 12), (42, 25)]]
        for left, right in zip(nodes, nodes[1:]):
            for a in left:
                for b in right: line(c, a, b, 0)
        for column in nodes:
            for x, y in column:
                round_shape(c, x, y, 4, 0)
                round_shape(c, x, y, 2, 1)
        letters = dict(FONT, N=['10001','11001','11001','10101','10011','10011','10001'])
        for n, ch in enumerate('NAM'):
            for y, row in enumerate(letters[ch]):
                for x, bit in enumerate(row):
                    if bit == '1': fill(c,52+n*24+x*4,6+y*3,55+n*24+x*4,8+y*3,0)
        for x in range(57, 119, 5): c.px(x, 30, 0)
        labels = ['INPUT', 'OUTPUT', 'MIX']
    elif kind == 'IR':
        word(c, 'IR', 12, 7, sx=7, sy=4, v=0)
        c.hline(65, 117, 26, 0)
        # One strong impulse, followed by an irregular decaying response.
        for x, h in [(68,20),(72,12),(77,16),(82,11),(87,8),(92,10),(97,6),(102,4),(107,5),(112,2)]:
            c.vline(x, 26-h, 26, 0)
        line(c, (62, 5), (119, 5), 0)
        line(c, (114, 3), (119, 5), 0)
        line(c, (114, 7), (119, 5), 0)
        labels = ['CAB', 'MIX', 'LEVEL']      # CabIR 0.20 page 1
    else: raise ValueError(kind)
    for x, label in zip((24,65,106), labels):
        c.draw_text(label, x-(len(label)*4-1)//2, 37)
        round_shape(c,x,53,7)
        round_shape(c,x,53,5,0)
        c.vline(x,49,53)
    return c

def picture(kind):
    return encode_zoom_rle(draw(kind))


# ---- Named covers: the loader draws the capture/cab name into the panel ----
# The loader (tools/cover_art.js) gets `named_base(kind)` as a bitmap and draws
# only the name, with the same rule as `draw_name` below; the two must stay in
# step (tools/tests/cover_art.test.cjs checks the JS against hashes recorded
# from this file). Templates reserve PICTURE_CAPACITY bytes for the RLE blob so
# any name fits without moving the rest of the file; unused bytes are zero.
NAME_BOX = (50, 6, 120, 25)          # x0, y0, x1, y1 inside the black panel
PICTURE_CAPACITY = 1024
KNOB_LABELS = {'NAM': ['INPUT', 'OUTPUT', 'MIX'], 'IR': ['MIX', 'LEVEL', 'RESO']}
TAGS = {'NAM': 'NAM', 'IR': 'CAB'}


def name_scale(n):
    """Block size for an n-character name: as large as fits NAME_BOX."""
    x0, y0, x1, y1 = NAME_BOX
    sx = max(1, min(5, ((x1 - x0 + 2) // max(1, n) - 1) // 3))
    sy = max(1, min(4, (y1 - y0 + 1) // 5, sx + 1))
    return sx, sy


# The 3x5 pedal font, with three glyphs fixed for names: its Y has no arms
# (reads as T) and its M and N are the same glyph. Local to the named covers so
# the effect pack's covers don't change.
NAME_FONT = dict(Canvas._FONT, Y=['101', '101', '010', '010', '010'], N=['111', '101', '101', '101', '101'])


def name_text(name):
    """Characters the font has: upper case; '_' and unknowns become spaces."""
    return ''.join(ch if ch in NAME_FONT else ' ' for ch in name.upper()[:8])


def name_word(c, text, x, y, sx, sy, v=0):
    """pack_covers.word with NAME_FONT."""
    for ch in text:
        for yy, row in enumerate(NAME_FONT[ch]):
            for xx, bit in enumerate(row):
                if bit == '1':
                    fill(c, x + xx * sx, y + yy * sy, x + (xx + 1) * sx - 1, y + (yy + 1) * sy - 1, v)
        x += 3 * sx + 1


def draw_name(c, name):
    text = name_text(name)
    if not text.strip():
        return
    sx, sy = name_scale(len(text))
    x0, y0, x1, y1 = NAME_BOX
    w, h = len(text) * (3 * sx + 1) - 1, 5 * sy
    name_word(c, text, x0 + (x1 - x0 + 1 - w) // 2, y0 + (y1 - y0 + 1 - h) // 2, sx, sy)


def named_base(kind):
    """The generic cover with no icon and no name: panel, kind tag, dials."""
    if kind not in TAGS:
        raise ValueError(kind)
    c = Canvas()
    c.rect(2, 1, 125, 63)
    fill(c, 5, 3, 122, 33)
    tag = TAGS[kind]
    word(c, tag, NAME_BOX[2] - (len(tag) * 4 - 1), 27, sx=1, sy=1, v=0)
    for x in range(NAME_BOX[0], NAME_BOX[2] - len(tag) * 4 - 1, 3):
        c.px(x, 29, 0)
    for x, label in zip((24, 65, 106), KNOB_LABELS[kind]):
        c.draw_text(label, x - (len(label) * 4 - 1) // 2, 37)
        round_shape(c, x, 53, 7)
        round_shape(c, x, 53, 5, 0)
        c.vline(x, 49, 53)
    return c


def named_canvas(kind, name='', icon=None):
    from capture_icons import draw_icon, DEFAULT_ICON
    c = named_base(kind)
    draw_icon(c, icon or DEFAULT_ICON[kind])
    draw_name(c, name)
    return c


def named_picture(kind, name='', icon=None):
    """RLE blob padded with zeros to PICTURE_CAPACITY (the template's reserved size)."""
    blob = encode_zoom_rle(named_canvas(kind, name, icon))
    assert len(blob) <= PICTURE_CAPACITY, f'{kind} cover for {name!r} is {len(blob)} B'
    return blob + bytes(PICTURE_CAPACITY - len(blob))
