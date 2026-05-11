#!/usr/bin/env python3
"""
Build TapeHack.ZDL by SPLICING our DSP into stock OptComp.ZDL.

Why this exists: our linker produces something subtly broken in the
3-param case (verified 2026-05-10 — TapeHKEx, a renamed clone of stock
Exciter, shows 3 knobs on hardware; a logically-equivalent build from
our linker shows only 2). The bug is somewhere in the descriptor /
imageInfo / dynsym / hash / .rela.dyn structure our linker emits, and
bisecting it costs hardware flashes.

Workaround: piggy-back on OptComp's known-good ELF structure. We:
  1. Load stock MS-70CDR_OPTCOMP.ZDL (3-param Dynamics, gid=1).
  2. Splice our compiled .audio section bytes into OptComp's audio
     function slot (Fx_DYN_OptComp at va=0..0xd60 = 3424 bytes; our
     DSP is 1760 bytes — fits with room to spare). Pad remainder
     with NOPs so handler VAs stay put.
  3. Rename the on-screen labels: "OptComp" → "TapeHack",
     "Drive"/"Tone"/"Level" → "Input"/"Drive"/"Output".
  4. Bump fxid to 0x0192 so it lives alongside stock OptComp rather
     than replacing it.

Known limitations:
  * The category icon stays Dynamics (gid=1). Cosmetic only.
  * OptComp's edit handlers scale knob values for OptComp's algorithm
    (e.g. Drive max=10, Tone max=100, Level max=150). Our DSP's
    params[5..7] arrive with whatever scaling OptComp's handlers do.
    Knob ranges may feel non-linear; tune the DSP constants if needed.
  * .audio MUST be self-contained (no external symbol references).
    Verified for current tapehack.c — it uses only stack locals and
    pointer arithmetic, no math.h, no external lookup tables.

Once our linker's 3-param bug is fixed, switch back to build.py.
"""
from __future__ import annotations
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X    = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99", "--opt_level=2", "-mv6740", "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]

TEMPLATE_PATH = ROOT / "working_zdls" / "MS-70CDR_OPTCOMP.ZDL"
ZDL_HDR_SIZE  = 76                  # ZDL wrapper before ELF
AUDIO_SLOT_SZ = 0x0d60              # Fx_DYN_OptComp size in stock OptComp


def compile_dsp() -> bytes:
    """Compile tapehack.c and return its .audio section bytes."""
    src = HERE / "tapehack.c"
    obj = HERE / "tapehack.obj"
    print(f"[template] compiling {src.name} → {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src), f"--output_file={obj}"],
        check=True, cwd=HERE,
    )

    data = obj.read_bytes()
    e_shoff   = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsz = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum   = struct.unpack_from("<H", data, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    sh = e_shoff + e_shstrndx*e_shentsz
    shstr_o = struct.unpack_from("<I", data, sh+0x10)[0]
    shstr_s = struct.unpack_from("<I", data, sh+0x14)[0]
    shstr = data[shstr_o:shstr_o+shstr_s]
    for i in range(e_shnum):
        h = e_shoff + i*e_shentsz
        name = shstr[struct.unpack_from("<I", data, h+0x00)[0]:].split(b"\x00",1)[0].decode()
        if name == ".audio":
            off = struct.unpack_from("<I", data, h+0x10)[0]
            sz  = struct.unpack_from("<I", data, h+0x14)[0]
            print(f"[template] .audio: {sz} bytes (slot capacity: {AUDIO_SLOT_SZ})")
            if sz > AUDIO_SLOT_SZ:
                raise SystemExit(f".audio size {sz} > slot {AUDIO_SLOT_SZ} — won't fit")
            return data[off:off+sz]
    raise SystemExit("no .audio section in tapehack.obj")


def patch_label_in_descriptor(zdl: bytearray, old: bytes, new: bytes) -> None:
    """Replace a descriptor entry name (12-byte slot, NUL-padded)."""
    needle = old + b"\x00" * (12 - len(old))
    i = zdl.find(needle, ZDL_HDR_SIZE)
    if i < 0:
        # Shorter forms — name may have leftover bytes from a previous longer name.
        # Be more lenient: just look for old bytes at start of a 12-byte slot.
        i = zdl.find(old, ZDL_HDR_SIZE)
        if i < 0:
            raise SystemExit(f"name slot {old!r} not found")
    new_slot = new + b"\x00" * (12 - len(new))
    zdl[i:i+12] = new_slot
    print(f"[template]   {old.decode():>10s} → {new.decode():<10s}  @ ELF+0x{i-ZDL_HDR_SIZE:x}")


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())

    # 1. Load template
    zdl = bytearray(TEMPLATE_PATH.read_bytes())
    print(f"[template] loaded {TEMPLATE_PATH.name} ({len(zdl)} bytes)")

    # 2. Compile + splice audio
    audio = compile_dsp()
    splice_off = ZDL_HDR_SIZE + 0x40   # PT_LOAD .text starts at file offset 0x40
    # Wait — that's the ELF program-header offset. The audio function is at
    # va=0 in .text, and .text's file offset depends on the template. For
    # OptComp specifically, .text section starts at file offset 0x40 in the
    # ELF (= ZDL+0x4c). Audio function at va=0 lives at the start of .text.
    # Verify by checking the ELF program headers.
    e_phoff   = struct.unpack_from("<I", zdl, ZDL_HDR_SIZE+0x1C)[0]
    e_phentsz = struct.unpack_from("<H", zdl, ZDL_HDR_SIZE+0x2A)[0]
    # First PT_LOAD = .text r-x
    p_offset = struct.unpack_from("<I", zdl, ZDL_HDR_SIZE+e_phoff+0x04)[0]
    p_vaddr  = struct.unpack_from("<I", zdl, ZDL_HDR_SIZE+e_phoff+0x08)[0]
    text_file_off = ZDL_HDR_SIZE + p_offset
    print(f"[template] .text @ ELF+0x{p_offset:x} (file 0x{text_file_off:x}), va=0x{p_vaddr:x}")

    # Splice: write our audio bytes, pad remainder of slot with NOPs (so the
    # rest of OptComp's handlers stay at their original VAs).
    NOP = b"\x00\x00\x00\x00"      # C6x NOP1 — single-cycle no-op
    pad_bytes = AUDIO_SLOT_SZ - len(audio)
    # Pad to 4-byte alignment with NOPs, then zeros if any (NOPs are 4-byte
    # so the whole slot stays valid)
    pad = NOP * (pad_bytes // 4) + b"\x00" * (pad_bytes % 4)
    zdl[text_file_off:text_file_off+AUDIO_SLOT_SZ] = audio + pad
    print(f"[template] spliced {len(audio)} bytes audio + {len(pad)} bytes NOP pad")

    # 3. Rename labels
    print(f"[template] relabeling:")
    patch_label_in_descriptor(zdl, b"OptComp", b"TapeHack")
    patch_label_in_descriptor(zdl, b"Drive",   b"Input")
    patch_label_in_descriptor(zdl, b"Tone",    b"Drive")
    patch_label_in_descriptor(zdl, b"Level",   b"Output")

    # 4. Bump fxid (matches manifest)
    fxid = manifest["fxid"]
    struct.pack_into('<H', zdl, 64, fxid)
    print(f"[template] fxid set to 0x{fxid:04x}")

    # 5. Save
    out = ROOT / "dist" / f"{manifest['effect_name']}.ZDL"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(bytes(zdl))
    print(f"\n[template] → {out} ({len(zdl)} bytes)")


if __name__ == "__main__":
    main()
