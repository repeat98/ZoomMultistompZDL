#!/usr/bin/env python3
"""Build Skull v0.05: a shaded 3D skull that reacts to the signal, idles with
animations when it's quiet, and explodes at the loudest (MS-70CDR 2.10), on zvis.

skull3d.py renders our own 3D skull model, lit and dithered to 1 bit: JAW_STEPS
jaw openings (the face), and SPIN_STEPS turns and ROLL_STEPS rolls for the idle
animations. Every frame is stored compressed per 128-byte block row (lz_row
below; skull.c's lz_row decodes it), so 28 frames fit in ~9 KB. The idle
timelines (look around, spin, roll, snake) are tables of frame numbers built
here; the explosion's shards and the dust are simulated in skull.c.
"""
import math
import random
import sys
import numpy as np
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "common"), str(HERE)]
from zvis_build import Canvas, raw, c_bytes, fill, encode_zoom_rle, build  # noqa: E402
import skull3d as S  # noqa: E402

PANEL = 63                         # full screen: the knob boxes are hidden at run time
CAM = dict(scale=0.0178, cy=31)    # skull fills the screen height
CX, CY = 62, 30                    # blast centre
JAW_STEPS = 6
JAW_MAX = 0.34                     # radians, fully open
SPIN_STEPS = 12                    # 30 degree turns
ROLL_STEPS = 8                     # 45 degrees: it rolls fast, and the file is near the size limit
SNAKE_JAW = 4                      # mouth open for the snake
SNAKE_LEN = 40                     # body points


def frame(**view):
    c = Canvas()
    fill(c, 0, 0, 127, PANEL)
    img, _ = S.render(h=64, **CAM, **view)
    bone = S.dither(S.tone(img), "bayer")
    for y in range(bone.shape[0]):
        for x in range(128):
            if bone[y, x]:
                c.px(x, y, 0)                      # bone is white on the black panel
    return c


jaws = [frame(jaw=JAW_MAX * k / (JAW_STEPS - 1)) for k in range(JAW_STEPS)]
spins = [frame(yaw=0.45 + 2 * math.pi * k / SPIN_STEPS) for k in range(1, SPIN_STEPS)]
rolls = [frame(roll=2 * math.pi * k / ROLL_STEPS) for k in range(1, ROLL_STEPS)]
frames = jaws + spins + rolls
SPIN0, ROLL0 = JAW_STEPS, JAW_STEPS + len(spins)
spin = lambda k: 0 if k % SPIN_STEPS == 0 else SPIN0 + k % SPIN_STEPS - 1
roll = lambda k: 0 if k % ROLL_STEPS == 0 else ROLL0 + k % ROLL_STEPS - 1


def lz_row(row):
    """One 128-byte block row: t < 0x80 = t+1 literal bytes follow; t >= 0x80 =
    copy t-0x80+3 bytes from (next byte)+1 back, within the row."""
    out, lit, i = bytearray(), bytearray(), 0

    def flush():
        nonlocal lit
        while lit:
            n = min(128, len(lit)); out.append(n - 1); out.extend(lit[:n]); lit = lit[n:]
    while i < len(row):
        best = (0, 0)
        for d in range(1, min(256, i) + 1):
            n = 0
            while i + n < len(row) and n < 130 and row[i + n - d] == row[i + n]:
                n += 1
            if n > best[0]:
                best = (n, d)
        if best[0] >= 3:
            flush(); out += bytes([0x80 + best[0] - 3, best[1] - 1]); i += best[0]
        else:
            lit.append(row[i]); i += 1
    flush()
    return bytes(out)


def unlz_row(data, at):                            # the decoder, mirrored from skull.c, to check
    d = bytearray()
    while len(d) < 128:
        t = data[at]; at += 1
        if t < 0x80:
            d += data[at:at + t + 1]; at += t + 1
        else:
            dist = data[at] + 1; at += 1
            for _ in range(t - 0x80 + 3):
                d.append(d[-dist])
    assert len(d) == 128
    return bytes(d)


lz, offs = bytearray(), []
for f in frames:
    r = raw(f)
    for b in range(8):
        offs.append(len(lz)); lz += lz_row(r[b * 128:(b + 1) * 128])
for i, f in enumerate(frames):
    assert b"".join(unlz_row(lz, offs[i * 8 + b]) for b in range(8)) == raw(f)
assert len(lz) < 65536


# Idle timelines: one frame number per shown frame (~30 per second).
def hold(seq, f, n):
    seq += [f] * n
look = []
for f, n in [(0, 8), (spin(-1), 3), (spin(-2), 26), (spin(-1), 3), (0, 12), (spin(1), 3), (spin(2), 26), (spin(1), 3), (0, 8)]:
    hold(look, f, n)
spinseq = []
for turn, holds in enumerate([[4, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2], [1] * 12, [1] * 12, [2, 2, 2, 2, 2, 2, 2, 3, 3, 3, 4, 4]]):
    for k, n in enumerate(holds):
        hold(spinseq, spin(k), n)
hold(spinseq, 0, 8)
rollseq = []
for f, n in [(0, 6), (roll(1), 8), (0, 3), (roll(-1), 8), (0, 8)]:
    hold(rollseq, f, n)
for k in range(1, ROLL_STEPS + 1):
    hold(rollseq, roll(k), 2)
for k in range(ROLL_STEPS - 1, -1, -1):
    hold(rollseq, roll(k), 2)
hold(rollseq, 0, 8)
seqs = [look, spinseq, rollseq]


# Snake: out of the left socket, down the cheek into the open mouth, out of the
# right socket; tongue flicks, then it pulls back the way it came.
def mouth_point():
    j = JAW_MAX * SNAKE_JAW / (JAW_STEPS - 1)
    lower = S.rot_x(np.array([0.0, -0.47, 0.36]), -j, np.array([0, -0.22, -0.05]))
    return S.project(((0.0 + lower[0]) / 2, (-0.39 + lower[1]) / 2, (0.37 + lower[2]) / 2), **CAM)


eyes = [S.project((sx * 0.17, -0.03, 0.34), **CAM) for sx in (-1, 1)]
(lx, ly), (rx, ry) = eyes
mx, my = mouth_point()


def spline(pts):
    """Catmull-Rom through pts, sampled so neighbours are <= 1 px apart."""
    pts = [pts[0]] + pts + [pts[-1]]
    out = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1:i + 3]
        n = int(max(abs(p2[0] - p1[0]), abs(p2[1] - p1[1])) * 2) + 1
        for k in range(n):
            t = k / n
            q = [0.5 * ((2 * p1[a]) + (-p0[a] + p2[a]) * t + (2 * p0[a] - 5 * p1[a] + 4 * p2[a] - p3[a]) * t * t
                        + (-p0[a] + 3 * p1[a] - 3 * p2[a] + p3[a]) * t ** 3) for a in (0, 1)]
            q = (round(q[0]), round(q[1]))
            if not out or q != out[-1][:2]:
                out.append(q)
    out.append((round(pts[-2][0]), round(pts[-2][1])))
    return out


HID = 0x80
path = [(lx, ly | HID)] * SNAKE_LEN                                   # coiled inside the head
path += [(x, y) for x, y in spline([(lx, ly), (lx - 9, ly - 5), (lx - 19, ly + 2), (lx - 21, ly + 14),
                                    (lx - 13, my + 7), (mx - 4, my + 2), (mx, my)])]
path += [(mx, my | HID)] * 14                                         # through the skull
path += [(x, y) for x, y in spline([(rx, ry), (rx + 7, ry - 6), (rx + 15, ry - 7), (rx + 21, ry - 2)])]
for x, y in path:
    assert 0 <= x < 128 and 0 <= (y & 63) < 64
assert len(path) < 256 and SNAKE_JAW < 8                            # packed in bytes for skull.c
end = len(path) - 1
snake = []                                                            # (jaw frame, head index, tongue)
for k in range(SNAKE_JAW + 1):
    snake += [(k, 0, 0)] * 2
s, t = 0, 0
while s < end:
    s = min(end, s + 2); t += 1
    snake.append((SNAKE_JAW, s, 1 if t % 18 < 3 and s > SNAKE_LEN + 4 else 0))
for k in range(30):
    snake.append((SNAKE_JAW, end, 1 if (k // 3) % 2 == 0 and k < 21 else 0))
while s > 0:
    s = max(0, s - 3); snake.append((SNAKE_JAW, s, 0))
for k in range(SNAKE_JAW, -1, -1):
    snake += [(k, 0, 0)] * 2


# Explosion sparks: fragments of lit bone flying outward from the blast centre
# (skull.c cuts the shards themselves from the picture).
def fragments(c, n=104, seed=7):
    rnd = random.Random(seed)
    cells = [(x, y) for y in range(0, PANEL - 1, 2) for x in range(0, 127, 2)
             if sum(1 for dy in (0, 1) for dx in (0, 1) if not c.pixels[y + dy][x + dx]) >= 2]
    rnd.shuffle(cells)
    out = []
    for x, y in sorted(cells[:n]):
        dx, dy = x - CX, (y - CY) * 1.4
        dist = max(1.0, math.hypot(dx, dy))
        speed = rnd.uniform(2.0, 5.0)
        vx = dx / dist * speed + rnd.uniform(-0.6, 0.6)
        vy = (dy / dist * speed) / 1.4 - rnd.uniform(0.8, 2.0)
        out.append((x, y, max(-127, min(127, round(vx * 16))), max(-127, min(127, round(vy * 16)))))
    return out


frag = fragments(jaws[0])
signed = lambda v: v & 0xFF
cos64 = [round(127 * math.cos(2 * math.pi * k / 64)) for k in range(64)]


def c_u16(name, vals):
    body = ",".join(str(v) for v in vals)
    return f"static const unsigned short {name}[{len(vals)}] = {{{body}}};\n"


seq_at = [0]
for q in seqs:
    seq_at.append(seq_at[-1] + len(q))
hdr = ["/* generated by build.py: our own 3D skull (skull3d.py), dithered */",
       f"#define SKULL_FRAGS {len(frag)}u", f"#define SKULL_CX {CX}", f"#define SKULL_CY {CY}",
       f"#define SKULL_JAW_STEPS {JAW_STEPS}u", f"#define SKULL_PANEL {PANEL}",
       f"#define SKULL_NFRAMES {len(frames)}u",
       f"#define SKULL_EYE_LX {lx}", f"#define SKULL_EYE_LY {ly}",
       f"#define SKULL_EYE_RX {rx}", f"#define SKULL_EYE_RY {ry}",
       f"#define SKULL_SEQ_LOOK {seq_at[0]}u", f"#define SKULL_SEQ_SPIN {seq_at[1]}u",
       f"#define SKULL_SEQ_ROLL {seq_at[2]}u", f"#define SKULL_SEQ_END {seq_at[3]}u",
       f"#define SKULL_PATH_N {len(path)}u", f"#define SKULL_SNAKE_N {len(snake)}u",
       f"#define SKULL_SNAKE_LEN {SNAKE_LEN}"]
(HERE / "skull_art.h").write_text(
    "\n".join(hdr) + "\n"
    + c_bytes("SKULL_LZ", bytes(lz)) + c_u16("SKULL_LZOFF", offs)
    + c_bytes("SKULL_SEQ", bytes(sum(seqs, [])))
    + c_bytes("SKULL_PX", bytes(p[0] for p in path)) + c_bytes("SKULL_PY", bytes(p[1] for p in path))
    + c_bytes("SKULL_SNAKE", bytes(v for j, s, tg in snake for v in (j | tg << 3, s)))
    + c_bytes("SKULL_FX", bytes(f[0] for f in frag)) + c_bytes("SKULL_FY", bytes(f[1] for f in frag))
    + c_bytes("SKULL_FVX", bytes(signed(f[2]) for f in frag))
    + c_bytes("SKULL_FVY", bytes(signed(f[3]) for f in frag))
    + c_bytes("SKULL_COS64", bytes(signed(v) for v in cos64)))
print(f"{len(frames)} frames, {len(lz)} bytes compressed; look {len(look)}, spin {len(spinseq)}, "
      f"roll {len(rollseq)}, snake {len(snake)} frames; eyes {eyes}, mouth {(mx, my)}")
if "--art-only" not in sys.argv:
    build(HERE, encode_zoom_rle(jaws[0]))
