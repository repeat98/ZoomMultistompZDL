"""Check that built ZDLs carry no code from Zoom's effects: no run of 16 or more bytes from the stock blobs the
linker used before own_runtime (docs/STOCK-FILES.md), which stay on your computer. LineSel's call stub and
push/pop helpers are TI's RTS code, which zui.asm also carries, so those ranges are left out.

    python3 build/check_no_stock.py dist/Loop.ZDL ... [--stock-dir build]
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from linker import _DLL_WORDS

WINDOW = 16
# LineSel blob offsets of TI's RTS helpers (LinkerConfig.handler_funcs): __c6xabi_call_stub, pop_rts, push_rts.
TI_RANGES = {"linesel_handlers.bin": [(0x140, 0x180), (0x1A0, 0x1E0)]}


def stock_windows(stock_dir: Path) -> dict[bytes, str]:
    sources = {"NoiseGate Dll_ (linker.py)": b"".join(struct.pack('<I', w) for w in _DLL_WORDS)}
    for name in ["linesel_handlers.bin", "air_knob3_edit.bin", "divf_rts.bin"]:
        path = stock_dir / name
        if not path.exists():
            sys.exit(f"{path} is missing: this check needs your local copies of the stock blobs")
        data = bytearray(path.read_bytes())
        for lo, hi in TI_RANGES.get(name, []):
            data[lo:hi] = bytes(hi - lo)            # zeros never match real code windows below
        sources[name] = bytes(data)
    windows = {}
    for label, data in sources.items():
        for i in range(len(data) - WINDOW + 1):
            chunk = data[i:i + WINDOW]
            if sum(1 for b in chunk if b) >= 6:   # NOP padding has at most one non-zero byte per word: not code
                windows.setdefault(chunk, f"{label}+0x{i:X}")
    return windows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("zdl", nargs="+", type=Path)
    ap.add_argument("--stock-dir", type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    windows, failed = stock_windows(args.stock_dir), 0
    for zdl in args.zdl:
        data = zdl.read_bytes()
        hits: dict[str, int] = {}
        for i in range(len(data) - WINDOW + 1):
            if data[i:i + WINDOW] in windows:
                source = windows[data[i:i + WINDOW]].rsplit('+', 1)[0]
                hits[source] = hits.get(source, 0) + 1
        print(f"{zdl.name}: " + ("no stock code" if not hits else "STOCK CODE: " + ", ".join(f"{k} ({n} windows)" for k, n in sorted(hits.items()))))
        failed += bool(hits)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
