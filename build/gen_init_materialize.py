#!/usr/bin/env python3
"""Assemble build/init_materialize.asm and emit the byte templates linker.py uses.

The `_init` that materializes params on load is written in assembly (see the
header of init_materialize.asm for why it exists and why it looks like that),
but the linker needs it as three byte strings it can repeat and patch. Those
strings used to be transcribed by hand into linker.py, which is a bad way to
carry machine code that hard-freezes a pedal when it is wrong.

So: assemble with TI's own asm6x, read the chunk boundaries out of the SYMBOL
TABLE rather than assuming any chunk is one 32-byte packet, and print the result
ready to paste -- or write it back into linker.py with --write.

    python3 build/gen_init_materialize.py            # show
    python3 build/gen_init_materialize.py --write    # update linker.py in place
"""

from __future__ import annotations
import argparse
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASM = ROOT / "init_materialize.asm"
LINKER = ROOT / "linker.py"

TI_ROOT = Path("/Applications/ti/ti-cgt-c6000_8.5.0.LTS")
# The cl6x driver, not asm6x directly: invoked on its own, asm6x exits 0 and
# silently writes nothing, which is a memorable half hour. cl6x -c assembles a
# .asm the same way the rest of the pack builds C.
ASM6X = TI_ROOT / "bin" / "cl6x"

# The chunks, in the order they appear, delimited by these symbols. The last
# entry is the end marker and produces no chunk of its own.
BOUNDARIES = [
    ("_INIT_MAT_PROLOGUE",   "_zdl_init_materialize"),
    ("_INIT_MAT_CALL_BLOCK", "_zdl_init_call_block"),
    ("_INIT_MAT_EPILOGUE",   "_zdl_init_epilogue"),
    (None,                   "_zdl_init_end"),
]


def _read_elf_sections(blob: bytes) -> dict:
    """Minimal ELF32 little-endian section reader: name -> (offset, size)."""
    if blob[:4] != b"\x7fELF":
        raise SystemExit("assembler output is not an ELF")
    e_shoff, = struct.unpack_from("<I", blob, 0x20)
    e_shentsize, = struct.unpack_from("<H", blob, 0x2E)
    e_shnum, = struct.unpack_from("<H", blob, 0x30)
    e_shstrndx, = struct.unpack_from("<H", blob, 0x32)

    def hdr(i):
        off = e_shoff + i * e_shentsize
        name, typ, flags, addr, offset, size, link, info, align, entsz = \
            struct.unpack_from("<10I", blob, off)
        return dict(name=name, type=typ, addr=addr, offset=offset, size=size,
                    link=link, entsize=entsz)

    shstr = hdr(e_shstrndx)
    def sname(n):
        end = blob.index(b"\0", shstr["offset"] + n)
        return blob[shstr["offset"] + n:end].decode()

    return {sname(hdr(i)["name"]): hdr(i) for i in range(e_shnum)}


def _symbols(blob: bytes, sections: dict) -> dict:
    sym = sections.get(".symtab")
    strt = sections.get(".strtab")
    if not sym or not strt:
        raise SystemExit("assembler output has no symbol table")
    out = {}
    count = sym["size"] // 16
    for i in range(count):
        off = sym["offset"] + i * 16
        st_name, st_value, st_size, st_info, st_other, st_shndx = \
            struct.unpack_from("<IIIBBH", blob, off)
        if not st_name:
            continue
        end = blob.index(b"\0", strt["offset"] + st_name)
        name = blob[strt["offset"] + st_name:end].decode()
        out[name] = (st_value, st_shndx)
    return out


def build_chunks() -> dict[str, bytes]:
    if not ASM6X.exists():
        raise SystemExit(f"TI assembler not found at {ASM6X}")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        obj = td / (ASM.stem + ".obj")
        # -mv6740: C674x, matching the rest of the pack. The driver writes
        # <stem>.obj into the working directory, so run it in the temp dir.
        proc = subprocess.run(
            [str(ASM6X), "-mv6740", "-c", str(ASM)],
            capture_output=True, text=True, cwd=td)
        if proc.returncode != 0:
            sys.stderr.write(proc.stdout + proc.stderr)
            raise SystemExit("asm6x failed")
        blob = obj.read_bytes()

    sections = _read_elf_sections(blob)
    syms = _symbols(blob, sections)
    text = sections.get(".text")
    if text is None:
        raise SystemExit("no .text in assembler output")
    body = blob[text["offset"]:text["offset"] + text["size"]]

    missing = [s for _, s in BOUNDARIES if s not in syms]
    if missing:
        raise SystemExit(f"missing symbols in assembler output: {missing}")

    addrs = [syms[s][0] for _, s in BOUNDARIES]
    if addrs != sorted(addrs):
        raise SystemExit(f"chunk symbols are out of order: {addrs}")

    chunks: dict[str, bytes] = {}
    for i, (const, symbol) in enumerate(BOUNDARIES[:-1]):
        start, end = addrs[i], addrs[i + 1]
        # Every chunk must START on a 32-byte fetch-packet boundary, or the
        # ADDKPC in the call block returns to the wrong place. That part the
        # .align directives guarantee and we only verify.
        if start % 32:
            raise SystemExit(
                f"{symbol}: chunk starts at 0x{start:x}, not on a 32-byte "
                f"fetch-packet boundary -- ADDKPC would resolve wrong")
        data = body[start:end]
        # Each chunk must also be a whole number of packets so that repeating it
        # keeps every later chunk aligned. A trailing .align does not pad the end
        # of the section, so pad here. 0x00000000 is NOP on C6x, and the padding
        # is either fallen through (prologue) or unreachable (after the return).
        if len(data) % 32:
            data += b"\0" * (32 - len(data) % 32)
        chunks[const] = data
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="rewrite the templates in linker.py in place")
    args = ap.parse_args()

    chunks = build_chunks()
    for name, data in chunks.items():
        print(f"{name}: {len(data)} bytes ({len(data)//32} packet(s))")
        print(f'    "{data.hex()}"')

    call = chunks["_INIT_MAT_CALL_BLOCK"]
    # The direct branch must stay at a fetch-packet boundary. Its immediate
    # points back to the block start until the linker patches the handler target.
    word, = struct.unpack_from("<I", call, 0x20)
    if word & ~(0x1FFFFF << 7) != 0x12:
        raise SystemExit(f"expected unpredicated B.S2 at +0x20, got {word:#010x}")
    displacement = (word >> 7) & 0x1FFFFF
    if displacement & (1 << 20):
        displacement -= 1 << 21
    if 0x20 + displacement * 4 != 0:
        raise SystemExit("branch placeholder no longer targets the block start")
    print("\npatch site OK: PC-relative B.S2 at +0x20")

    if not args.write:
        print("\n(run with --write to update linker.py)")
        return 0

    src = LINKER.read_text()
    for name, data in chunks.items():
        pat = re.compile(rf'{re.escape(name)} = bytes\.fromhex\(\s*"[0-9a-f"\s]*?"\s*\)',
                         re.MULTILINE)
        if not pat.search(src):
            raise SystemExit(f"could not find {name} assignment in linker.py")
        src = pat.sub(f'{name} = bytes.fromhex(\n    "{data.hex()}")', src, count=1)
    LINKER.write_text(src)
    print(f"\nwrote {len(chunks)} template(s) into {LINKER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
