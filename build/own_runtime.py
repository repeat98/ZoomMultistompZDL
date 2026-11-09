"""The effect's own runtime: no code from Zoom's effects in a built ZDL.

Leemuzhko's zui.asm (OnOff and knob edit handlers, written from the documented edit-handler ABI, with TI's
call stub and push/pop helpers from TI's RTS source) and dll.asm (the Dll_ entry), in build/runtime/ with their
licence, assembled with TI's assembler. LinkerConfig(own_runtime=True) uses them in place of
linesel_handlers.bin, air_knob3_edit.bin, the LineSel clones and the NoiseGate-derived Dll_, and generates the
.c6xabi.attributes section instead of copying it (docs/STOCK-FILES.md).
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from pathlib import Path

from linker import ObjFile

RUNTIME = Path(__file__).resolve().parent / "runtime"
TI_ROOT = Path(os.environ.get("TI_CGT", "/Applications/ti/ti-cgt-c6000_8.5.0.LTS"))
# Relocation types TI's assembler adds as layout markers (R_C6000_ALIGN, FPHEAD_BEGIN, NOCMP): not addresses.
LAYOUT_MARKERS = range(253, 256)


def _assemble(text: str, stem: str, *flags: str) -> ObjFile:
    work = Path(tempfile.mkdtemp(prefix="zdl_runtime_"))
    src, obj = work / f"{stem}.asm", work / f"{stem}.obj"
    src.write_text(text, encoding="utf-8", newline="\n")
    r = subprocess.run([str(TI_ROOT / "bin" / "cl6x"), "-mv6740", "--abi=eabi", *flags, str(src), f"--output_file={obj}"],
                       cwd=work, capture_output=True, text=True)
    if r.returncode or not obj.exists():
        raise RuntimeError(f"{stem}.asm: TI's assembler failed (TI_CGT={TI_ROOT}):\n{r.stdout}{r.stderr}")
    return ObjFile(obj)


def _text(obj: ObjFile) -> dict:
    text = [s for s in obj.sections if s['name'].startswith('.text') and s['size']]
    if len(text) != 1:
        raise RuntimeError(f"expected one code section, got {[s['name'] for s in text]}")
    return text[0]


def handlers(indices: list[int]) -> tuple[bytes, dict[str, int]]:
    """zui.asm plus one entry per knob (parameter index i: knob id i + 2, parameter at byte 20 + 4 * i, as LineSel's
    handlers). Returns the code, which has no relocations, and the offsets of onf, knob, stub, push_rts, pop_rts and
    k<i>."""
    entries = "".join(f"zui_k{i}:\n        B.S1        zui_knob\n        MVK.L2      {i + 2},B4\n"
                      f"        MVK.S1      {20 + 4 * i},A1\n        NOP         3\n" for i in indices)
    obj = _assemble((RUNTIME / "zui.asm").read_text(encoding="utf-8") + entries, "zui")
    text = _text(obj)
    if any(rel['type'] not in LAYOUT_MARKERS for rel in obj.relocs.get(text['idx'], [])):
        raise RuntimeError("zui: a relocation in the code; every branch target must be local")
    offsets = {s['name'][4:]: s['value'] for s in obj.symbols if s['shndx'] == text['idx'] and s['name'].startswith('zui_')}
    missing = [n for n in ['onf', 'knob', 'stub', 'push_rts', 'pop_rts', *(f'k{i}' for i in indices)] if n not in offsets]
    if missing:
        raise RuntimeError(f"zui: symbols missing: {missing}")
    return bytes(text['data']), offsets


def dll(rows: int, size: int) -> tuple[bytes, list[tuple[int, int, str]]]:
    """dll.asm with `rows` descriptor rows, padded with NOPs to `size` bytes, and its four address relocations
    (offset, type, 'desc' | 'info'). The row count's place is found by assembling with 0 and 1 and comparing."""
    if not 0 < rows <= 15:
        raise ValueError(f"Dll_ row count {rows} doesn't fit MVK.L1")
    source = (RUNTIME / "dll.asm").read_text(encoding="utf-8")
    marker = "MVK.L1  0,A0"
    if source.count(marker) != 1:
        raise RuntimeError("dll.asm: row-count instruction not found")
    codes, relocs = [], []
    for count in (0, 1):
        obj = _assemble(source.replace(marker, f"MVK.L1  {count},A0"), f"dll{count}", "--no_compress")
        text = _text(obj)
        codes.append(bytes(text['data']))
        if count == 0:
            for rel in obj.relocs.get(text['idx'], []):
                if rel['type'] in LAYOUT_MARKERS:
                    continue
                purpose = {'zdl_desc': 'desc', 'zdl_info': 'info'}.get(obj.symbols[rel['sym_idx']]['name'])
                if purpose is None:
                    raise RuntimeError(f"dll.asm: unexpected relocation to {obj.symbols[rel['sym_idx']]['name']!r}")
                relocs.append((rel['offset'], rel['type'], purpose))
    word = [i for i in range(0, len(codes[0]), 4) if codes[0][i:i + 4] != codes[1][i:i + 4]]
    if len(word) != 1 or len(relocs) != 4 or len(codes[0]) > size:
        raise RuntimeError(f"dll.asm: unexpected layout (count words {word}, relocations {len(relocs)}, {len(codes[0])} bytes)")
    body = bytearray(size)                                   # zero words are NOPs
    body[:len(codes[0])] = codes[0]
    struct.pack_into('<I', body, word[0], struct.unpack_from('<I', body, word[0])[0] | (rows << 18))
    return bytes(body), sorted(relocs)


def _uleb(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


# The .c6xabi.attributes of the bare-metal, non-DSBT, non-PIC C674x model the linker produces (TI SPRAB89B
# chapter 17): the TI vendor block's tag/value pairs and the generic block's Tag_File body.
_TI_ATTRIBUTES = ((8, 8), (10, 4), (12, 8), (256, 8), (258, 2), (260, 2), (270, 2), (272, 3))
_GENERIC_ATTRIBUTES = b"\x04\x08\x06\x01"


def abi_attributes() -> bytes:
    def sub(vendor: bytes, body: bytes) -> bytes:
        return struct.pack("<I", 4 + len(vendor) + 1 + len(body)) + vendor + b"\x00" + body
    ti_body = b"\x05Linker\x00" + b"".join(_uleb(t) + _uleb(v) for t, v in _TI_ATTRIBUTES)
    return (b"A" + sub(b"TI", b"\x01" + struct.pack("<I", 5 + len(ti_body)) + ti_body)
            + sub(b"c6xabi", b"\x01" + struct.pack("<I", 5 + len(_GENERIC_ATTRIBUTES)) + _GENERIC_ATTRIBUTES))
