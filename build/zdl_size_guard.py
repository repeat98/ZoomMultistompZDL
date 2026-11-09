"""The pedal refuses (freezes on load) ZDLs above a size cap.

Hardware, 2026-09-30/10-02 (NAM bisect): every file up to 32,126 bytes
(code+data 29,576) loaded; NAM 0.24 at 32,998 (30,336) and TSize2 -- the
working 0.23 padded with dead data -- at 33,174 (30,512) froze. The cap lies
in between; a 32 KB (32,768-byte) file limit fits both sides. Until it is
pinned down, release builds must stay within the largest PROVEN sizes.

Independent measurements agree (github.com/Leemuzhko/ZOOM_development
SDK/LIMITS.md, MS-Series): code+const 30,032 B passed / 30,096 failed for one
layout family, 29,960 / 30,216 for another, 28,904 working -- a code+data cap
near 30 KB that shifts a little with layout, not a universal number. Our
29,576 stays the bound because it is proven on OUR layout.
"""
import struct
from pathlib import Path

MAX_FILE = 32126          # largest file proven to load (tsize)
MAX_CODE_DATA = 29576     # its text + const


def sizes(path):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from zdl import Zdl
    data = Path(path).read_bytes()
    e = Zdl.load(path).elf
    phoff, = struct.unpack_from('<I', e, 28)
    phsz, phn = struct.unpack_from('<HH', e, 42)
    loads = [struct.unpack_from('<8I', e, phoff + i * phsz) for i in range(phn)]
    text_const = sum(seg[4] for seg in loads if seg[0] == 1 and seg[6] in (4, 5))
    return len(data), text_const


def check(path):
    n, tc = sizes(path)
    if n > MAX_FILE or tc > MAX_CODE_DATA:
        raise SystemExit(f'{Path(path).name}: {n} bytes (code+data {tc}) is over the proven pedal size '
                         f'({MAX_FILE} / {MAX_CODE_DATA}); larger files froze the pedal on load. '
                         'See build/zdl_size_guard.py.')
    return n, tc
