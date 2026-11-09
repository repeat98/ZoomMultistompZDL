"""Icons for named NAM / CabIR covers, picked in the loader.

Each icon draws white-on-black (v=0) inside the cover's black panel, in a
40 x 28 box whose top-left is ICON_ORIGIN. The LCD stretches pixels ~1.4x
vertically, so round things use stock_style_covers.round_shape (aspect-
corrected) and boxes are drawn a little flatter than they should look.
The loader gets each icon as a pixel mask (package_generated_slots.cover_block),
so these functions run only here.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/airwindows/common'))
from stock_style_covers import fill, line, round_shape

ICON_ORIGIN = (6, 4)
ICON_SIZE = (40, 28)


def _at(c):
    ox, oy = ICON_ORIGIN

    class P:
        def px(self, x, y, v=0): c.px(ox + x, oy + y, v)
        def h(self, x0, x1, y, v=0): c.hline(ox + x0, ox + x1, oy + y, v)
        def v(self, x, y0, y1, v=0): c.vline(ox + x, oy + y0, oy + y1, v)
        def box(self, x0, y0, x1, y1, v=0): c.rect(ox + x0, oy + y0, ox + x1, oy + y1, v)
        def fill(self, x0, y0, x1, y1, v=0): fill(c, ox + x0, oy + y0, ox + x1, oy + y1, v)
        def line(self, a, b, v=0): line(c, (ox + a[0], oy + a[1]), (ox + b[0], oy + b[1]), v)
        def ring(self, x, y, r, v=0): round_shape(c, ox + x, oy + y, r, v, filled=False)
        def dot(self, x, y, r, v=0): round_shape(c, ox + x, oy + y, r, v)
    return P()


def lattice(p):                                     # the original NAM mark
    nodes = [[(6, 8), (6, 21)], [(20, 4), (20, 14), (20, 24)], [(34, 8), (34, 21)]]
    for left, right in zip(nodes, nodes[1:]):
        for a in left:
            for b in right: p.line(a, b)
    for col in nodes:
        for x, y in col:
            p.dot(x, y, 4); p.dot(x, y, 2, 1)


def impulse(p):                                     # the original IR mark
    p.h(2, 38, 24)
    for x, h in [(4, 21), (8, 13), (12, 16), (16, 11), (20, 9), (24, 10), (28, 6), (32, 4), (36, 2)]:
        p.v(x, 24 - h, 24)


def amp(p):                                         # amp head: knobs over a grille
    p.box(1, 3, 38, 25); p.box(2, 4, 37, 24)
    p.h(4, 35, 9)
    for x in range(7, 35, 5): p.dot(x, 6, 1)
    for y in range(12, 23, 2): p.h(5, 34, y)
    p.h(16, 23, 1); p.v(16, 1, 3); p.v(23, 1, 3)


def cabinet(p):                                     # 2x2 speaker cab
    p.box(2, 0, 37, 27); p.box(3, 1, 36, 26)
    for x in (12, 27):
        for y in (7, 20):
            p.ring(x, y, 6); p.dot(x, y, 1)


def speaker(p):                                     # one big cone
    p.ring(20, 14, 18); p.ring(20, 14, 13); p.ring(20, 14, 7); p.dot(20, 14, 3)


def tube(p):                                        # a valve
    p.ring(20, 9, 9)
    p.v(11, 9, 22); p.v(29, 9, 22); p.h(11, 29, 22)
    p.fill(13, 23, 27, 25)
    for x in (15, 20, 25): p.v(x, 26, 27)
    p.box(16, 8, 24, 18); p.line((18, 11), (22, 15))


def microphone(p):                                  # SM57-style, angled
    p.line((6, 24), (24, 6)); p.line((9, 27), (27, 9)); p.line((6, 24), (9, 27))
    p.dot(30, 6, 7); p.dot(30, 6, 5, 1)
    for d in (-3, 0, 3): p.line((27 + d, 3), (33 + d, 9))


def lightning(p):
    pts = [(24, 0), (10, 15), (19, 15), (14, 27), (30, 10), (21, 10), (26, 0)]
    for a, b in zip(pts, pts[1:] + pts[:1]): p.line(a, b)
    p.fill(18, 4, 22, 9); p.fill(15, 12, 24, 14); p.fill(17, 17, 21, 20)


def flame(p):
    for row, (a, b) in enumerate([(19, 20), (18, 21), (18, 22), (17, 23), (16, 24), (15, 25), (14, 26), (13, 27),
                                  (12, 28), (11, 28), (11, 29), (10, 29), (10, 30), (10, 30), (9, 30), (9, 31),
                                  (9, 31), (9, 31), (10, 31), (10, 30), (11, 29), (12, 28), (13, 27), (15, 25),
                                  (17, 23)]):
        p.h(a, b, row + 2)
    for row, (a, b) in enumerate([(19, 20), (18, 21), (17, 22), (17, 23), (16, 23), (16, 24), (16, 24), (17, 23),
                                  (18, 22)]):
        p.h(a, b, row + 16, 1)


def skull(p):
    p.dot(20, 11, 14)
    p.fill(12, 20, 28, 25)
    p.dot(14, 11, 4, 1); p.dot(26, 11, 4, 1)
    p.fill(19, 16, 21, 18, 1)
    for x in (14, 18, 22, 26): p.v(x, 22, 25, 1)


def guitar(p):                                      # body + neck
    p.dot(13, 20, 9); p.dot(18, 13, 6)
    p.dot(13, 20, 3, 1)
    p.fill(19, 9, 21, 12, 1)
    p.line((18, 15), (36, 1)); p.line((19, 16), (37, 2)); p.fill(35, 0, 38, 3)


def sine(p):
    import math
    last = None
    for x in range(0, 40):
        q = (x, round(14 - 10 * math.sin(x * 2 * math.pi / 20)))
        if last: p.line(last, q)
        last = q
    p.h(0, 39, 14)


def square(p):                                      # fuzz / clipped wave
    y = 4
    for x0 in range(0, 40, 10):
        p.h(x0, x0 + 5, 4); p.v(x0 + 5, 4, 24); p.h(x0 + 5, x0 + 10, 24); p.v(x0 + 10, 4, 24)


def star(p):
    import math
    pts = []
    for k in range(10):
        r = 15 if k % 2 == 0 else 6
        a = -math.pi / 2 + k * math.pi / 5
        pts.append((round(20 + r * math.cos(a)), round(14 + r * math.sin(a) / 1.4)))
    for a, b in zip(pts, pts[1:] + pts[:1]): p.line(a, b)
    p.dot(20, 14, 4)


def moon(p):
    p.dot(15, 14, 13); p.dot(21, 11, 11, 1)
    p.dot(32, 5, 1); p.dot(34, 18, 1); p.px(28, 24); p.px(37, 10)


def eye(p):
    import math
    for x in range(2, 39):
        d = round(10 * math.sin((x - 2) / 36 * math.pi))
        p.px(x, 14 - d); p.px(x, 14 + d)
    p.dot(20, 14, 7); p.dot(20, 14, 3, 1)


def crown(p):
    pts = [(3, 22), (3, 6), (12, 15), (20, 3), (28, 15), (37, 6), (37, 22)]
    for a, b in zip(pts, pts[1:]): p.line(a, b)
    p.fill(3, 21, 37, 25)
    for x in (3, 20, 37): p.dot(x, 3 if x == 20 else 5, 2)


def heart(p):
    p.dot(12, 8, 8); p.dot(28, 8, 8)
    for row in range(9, 27):
        half = round((26 - row) * 1.15)
        p.h(20 - half, 20 + half, row)
    for y in range(0, 6):                           # the notch between the lobes
        p.h(20 - (5 - y), 20 + (5 - y), y, 1)


def gem(p):
    pts = [(10, 3), (30, 3), (38, 10), (20, 26), (2, 10)]
    for a, b in zip(pts, pts[1:] + pts[:1]): p.line(a, b)
    p.h(2, 38, 10)
    for a, b in [((10, 3), (15, 10)), ((30, 3), (25, 10)), ((15, 10), (20, 26)), ((25, 10), (20, 26)),
                 ((20, 3), (15, 10)), ((20, 3), (25, 10))]:
        p.line(a, b)


def ghost(p):
    p.dot(20, 10, 12)
    p.fill(9, 10, 31, 23)
    for x in range(9, 32, 6): p.fill(x, 24, x + 2, 26)
    p.dot(15, 10, 2, 1); p.dot(25, 10, 2, 1)
    p.fill(18, 16, 22, 18, 1)


def headphones(p):
    import math
    for k in range(0, 181, 3):
        a = math.radians(180 + k)
        p.px(round(20 + 16 * math.cos(a)), round(18 + 15 * math.sin(a)))
        p.px(round(20 + 14 * math.cos(a)), round(18 + 13 * math.sin(a)))
    p.fill(2, 16, 8, 27); p.fill(32, 16, 38, 27)


ICONS = [
    ('lattice', 'Network', lattice), ('impulse', 'Impulse', impulse), ('amp', 'Amp head', amp),
    ('cabinet', 'Cabinet', cabinet), ('speaker', 'Speaker', speaker), ('tube', 'Tube', tube),
    ('mic', 'Mic', microphone), ('bolt', 'Lightning', lightning), ('flame', 'Flame', flame),
    ('skull', 'Skull', skull), ('guitar', 'Guitar', guitar), ('sine', 'Sine wave', sine),
    ('square', 'Square wave', square), ('star', 'Star', star), ('moon', 'Moon', moon),
    ('eye', 'Eye', eye), ('crown', 'Crown', crown), ('heart', 'Heart', heart),
    ('gem', 'Gem', gem), ('ghost', 'Ghost', ghost), ('headphones', 'Headphones', headphones),
]
DEFAULT_ICON = {'NAM': 'lattice', 'IR': 'impulse'}


def draw_icon(c, icon_id):
    fn = next(f for i, _, f in ICONS if i == icon_id)
    fn(_at(c))
