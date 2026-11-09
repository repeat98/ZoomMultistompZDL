"""Decode a .ZDL's on-device cover (picEffectType_*) back to pixels.

The inverse of screen_image.encode_zoom_rle. Also reads effectTypeImageInfo
to recover the declared image size and the live knob-value box positions the
firmware paints on top of the cover at runtime.

Usage:
    python3 build/decode_picture.py path/to/Effect.ZDL [--png out.png] [--scale 4]

Findings this tool established (vs 130 stock MS-70CDR ZDLs):
  * The cover picture is the FULL 128x64 frame (not 128x40) — every stock
    effect declares height=64.
  * Knob-value boxes (20x15 px each, up to 3 shown) are NOT in the picture;
    the firmware composites them over the cover at the (x,y) in image_info.
"""

from __future__ import annotations

import struct
import sys


def _elf(path: str):
    d = open(path, "rb").read()
    base = d.find(b"\x7fELF")
    if base < 0:
        raise ValueError("no ELF magic (not a .ZDL?)")

    def u(fmt, o):
        return struct.unpack_from(fmt, d, base + o)

    e_shoff, = u("<I", 0x20)
    e_shentsize, = u("<H", 0x2E)
    e_shnum, = u("<H", 0x30)
    secs = []
    for k in range(e_shnum):
        b = base + e_shoff + k * e_shentsize
        nm, typ, fl, addr, off, size, link, info, al, es = struct.unpack_from("<10I", d, b)
        secs.append(dict(typ=typ, addr=addr, off=off, size=size, link=link, entsz=es))
    return d, base, secs


def _va_to_off(d, base, secs, va):
    for s in secs:
        if s["addr"] and s["addr"] <= va < s["addr"] + s["size"]:
            return base + s["off"] + (va - s["addr"])
    return None


def _find_symbol(d, base, secs, prefix):
    sym = next(s for s in secs if s["typ"] in (11, 2))
    strs = secs[sym["link"]]
    strtab = d[base + strs["off"]: base + strs["off"] + strs["size"]]
    # Effects ship BOTH `picEffectType_<name>` (the full 128x64 cover) and
    # `picEffectTypeKnob_<name>` (a small knob graphic). The loose prefix matches
    # both; grabbing the Knob one decodes to garbage. Prefer the real cover;
    # fall back to the Knob symbol only if no plain cover exists.
    fallback = (None, None)
    for k in range(sym["size"] // sym["entsz"]):
        b = base + sym["off"] + k * sym["entsz"]
        st_name, st_value, st_size, info, other, shndx = struct.unpack_from("<IIIBBH", d, b)
        end = strtab.index(b"\0", st_name)
        name = strtab[st_name:end].decode("latin1")
        if not name.startswith(prefix):
            continue
        if "Knob" in name:
            if fallback[0] is None:
                fallback = (name, st_value)
            continue
        return name, st_value
    return fallback


def decode_picture(path: str):
    """Return (pixels[64][128], symbol_name)."""
    d, base, secs = _elf(path)
    name, va = _find_symbol(d, base, secs, "picEffectType")
    if va is None:
        raise ValueError("no picEffectType symbol")
    off = _va_to_off(d, base, secs, va)
    raw, i = [], off
    while len(raw) < 1024 and i < len(d) - 1:
        x = d[i]
        if d[i + 1] == x:                 # doubled marker + run-length byte
            raw += [x] * (d[i + 2] + 2)
            i += 3
        else:
            raw.append(x)
            i += 1
    raw = (raw + [0] * 1024)[:1024]
    px = [[0] * 128 for _ in range(64)]
    idx = 0
    for yx in range(8):                   # 8 row-blocks of 8 vertical pixels
        for x in range(128):
            byte = raw[idx]
            idx += 1
            for z in range(8):
                if byte & (1 << z):
                    px[yx * 8 + z][x] = 1
    return px, name


def read_image_info(path: str):
    """Return dict(width, height, count, knobs=[(id,x,y), ...])."""
    d = open(path, "rb").read()
    sig = struct.pack("<4I", 0, 1, 0, 128)   # 0,1,0,width=128
    i = d.find(sig)
    if i < 0:
        return None
    off = i + 16
    height, = struct.unpack_from("<I", d, off); off += 4
    off += 4                                  # picture pointer
    off += 8                                  # two header words
    count, = struct.unpack_from("<I", d, off); off += 4
    knobs = []
    for _ in range(3):
        kid, kx, ky, kptr = struct.unpack_from("<4I", d, off); off += 16
        if kid:
            knobs.append((kid, kx, ky))
    return dict(width=128, height=height, count=count, knobs=knobs)


def render_png(path: str, out: str, scale: int = 5, show_knobs: bool = True):
    from PIL import Image, ImageDraw

    px, _ = decode_picture(path)
    info = read_image_info(path)
    W, H = 128, 64
    bg, lit = (18, 20, 24), (180, 230, 255)
    img = Image.new("RGB", (W * scale, H * scale), bg)
    dr = ImageDraw.Draw(img)
    for y in range(H):
        for x in range(W):
            if px[y][x]:
                dr.rectangle([x * scale, y * scale, x * scale + scale - 1, y * scale + scale - 1], fill=lit)
    if show_knobs and info:
        for kid, kx, ky in info["knobs"]:     # 20x15 firmware-painted boxes
            dr.rectangle([kx * scale, ky * scale, (kx + 20) * scale, (ky + 15) * scale],
                         outline=(255, 120, 120), width=max(1, scale // 2))
    img.save(out)
    return info


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)
    zdl = args[0]
    png = None
    scale = 5
    if "--png" in args:
        png = args[args.index("--png") + 1]
    if "--scale" in args:
        scale = int(args[args.index("--scale") + 1])
    info = read_image_info(zdl)
    print(f"{zdl}: declared {info['width']}x{info['height']}, "
          f"param_count={info['count']}, knob_boxes={info['knobs']}")
    if png:
        render_png(zdl, png, scale=scale)
        print(f"  -> wrote {png}")
