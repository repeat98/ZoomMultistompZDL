#!/usr/bin/env python3
"""
Wrap extracted Main.bin chunks as minimal C6x ELF objects so dis6x can
disassemble them. Each .bin in firmware/extracted/ is named after its
load address; we emit a parallel .out file with .text mapped to that VA.

This wrapper now includes a `.c6xabi.attributes` section declaring the
target ISA (C674x) so dis6x decodes 16-bit compact instructions
correctly. Without that hint, half the firmware shows up as ".word"
because dis6x falls back to the conservative 32-bit-only decode.

Usage:
    python3 firmware/wrap_for_dis6x.py
    dis6x firmware/extracted/chunk_<addr>_<size>.out > out.dis
"""
from __future__ import annotations
import struct
from pathlib import Path

ET_DYN              = 3
EM_TI_C6000         = 140
SHT_NULL            = 0
SHT_PROGBITS        = 1
SHT_STRTAB          = 3
SHT_C6000_ATTRIBUTES = 0x70000003
SHT_TI_SH_FLAGS     = 0x7F000005
SHF_ALLOC           = 2
SHF_EXECINSTR       = 4
PT_LOAD             = 1

HERE = Path(__file__).resolve().parent

# Both blobs were extracted from a fresh cl6x output (probe.obj) so
# dis6x recognises them as native. The .c6xabi.attributes blob includes
# all the TI extension tags the assembler emits; the .TI.section.flags
# section is what actually tells dis6x "this section uses compact
# instructions" — without it, dis6x falls back to 32-bit-only decode
# and ~63% of the firmware shows up as raw .word.
_PROBE_ATTRS_PATH = HERE / "probe_c6xabi_attrs.bin"
_PROBE_TI_FLAGS_PATH = HERE / "probe_TI_section_flags.bin"


def wrap(payload: bytes, load_addr: int) -> bytes:
    text_size = len(payload)
    attrs_data = _PROBE_ATTRS_PATH.read_bytes()
    ti_flags_data = _PROBE_TI_FLAGS_PATH.read_bytes()

    shstr = b"\x00.text\x00.c6xabi.attributes\x00.TI.section.flags\x00.shstrtab\x00"
    name_text         = shstr.index(b".text\x00")
    name_attrs        = shstr.index(b".c6xabi.attributes\x00")
    name_ti_flags     = shstr.index(b".TI.section.flags\x00")
    name_shstrtab     = shstr.index(b".shstrtab\x00")

    ELF_HDR   = 0x34
    PHDR_SIZE = 0x20
    NUM_PHDRS = 1
    SHDR_SIZE = 0x28
    NUM_SHDRS = 5    # NULL, .text, .c6xabi.attributes, .TI.section.flags, .shstrtab

    text_off     = ELF_HDR + NUM_PHDRS * PHDR_SIZE
    attrs_off    = text_off + text_size
    ti_flags_off = attrs_off + len(attrs_data)
    shstr_off    = ti_flags_off + len(ti_flags_data)
    shdr_off     = shstr_off + len(shstr)
    elf_size     = shdr_off + NUM_SHDRS * SHDR_SIZE

    elf = bytearray(elf_size)
    elf[:4] = b"\x7fELF"
    elf[4]  = 1                                # ELFCLASS32
    elf[5]  = 1                                # ELFDATA2LSB
    elf[6]  = 1                                # EV_CURRENT
    elf[7]  = 0x40                             # ELFOSABI_C6000_ELFABI
    struct.pack_into("<H", elf, 0x10, ET_DYN)
    struct.pack_into("<H", elf, 0x12, EM_TI_C6000)
    struct.pack_into("<I", elf, 0x14, 1)
    struct.pack_into("<I", elf, 0x18, load_addr)
    struct.pack_into("<I", elf, 0x1C, ELF_HDR)
    struct.pack_into("<I", elf, 0x20, shdr_off)
    struct.pack_into("<I", elf, 0x24, 0)
    struct.pack_into("<H", elf, 0x28, ELF_HDR)
    struct.pack_into("<H", elf, 0x2A, PHDR_SIZE)
    struct.pack_into("<H", elf, 0x2C, NUM_PHDRS)
    struct.pack_into("<H", elf, 0x2E, SHDR_SIZE)
    struct.pack_into("<H", elf, 0x30, NUM_SHDRS)
    struct.pack_into("<H", elf, 0x32, NUM_SHDRS - 1)        # e_shstrndx

    # PT_LOAD program header (executable .text)
    p = ELF_HDR
    struct.pack_into("<I", elf, p+0x00, PT_LOAD)
    struct.pack_into("<I", elf, p+0x04, text_off)
    struct.pack_into("<I", elf, p+0x08, load_addr)
    struct.pack_into("<I", elf, p+0x0C, load_addr)
    struct.pack_into("<I", elf, p+0x10, text_size)
    struct.pack_into("<I", elf, p+0x14, text_size)
    struct.pack_into("<I", elf, p+0x18, 5)                  # PF_R | PF_X
    struct.pack_into("<I", elf, p+0x1C, 32)

    elf[text_off:text_off+text_size]              = payload
    elf[attrs_off:attrs_off+len(attrs_data)]      = attrs_data
    elf[ti_flags_off:ti_flags_off+len(ti_flags_data)] = ti_flags_data
    elf[shstr_off:shstr_off+len(shstr)]           = shstr

    def _sh(idx, name_off, sh_type, flags, addr, off, sz, link=0, info=0, align=0, entsize=0):
        o = shdr_off + idx * SHDR_SIZE
        struct.pack_into("<I", elf, o+0x00, name_off)
        struct.pack_into("<I", elf, o+0x04, sh_type)
        struct.pack_into("<I", elf, o+0x08, flags)
        struct.pack_into("<I", elf, o+0x0C, addr)
        struct.pack_into("<I", elf, o+0x10, off)
        struct.pack_into("<I", elf, o+0x14, sz)
        struct.pack_into("<I", elf, o+0x18, link)
        struct.pack_into("<I", elf, o+0x1C, info)
        struct.pack_into("<I", elf, o+0x20, align)
        struct.pack_into("<I", elf, o+0x24, entsize)

    _sh(0, 0, SHT_NULL, 0, 0, 0, 0)
    _sh(1, name_text, SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR,
        load_addr, text_off, text_size, align=32)
    _sh(2, name_attrs, SHT_C6000_ATTRIBUTES, 0,
        0, attrs_off, len(attrs_data), align=1)
    # SHT_TI_SH_FLAGS link/info point at the section it annotates (.text=1).
    _sh(3, name_ti_flags, SHT_TI_SH_FLAGS, 0,
        0, ti_flags_off, len(ti_flags_data), link=1, align=1)
    _sh(4, name_shstrtab, SHT_STRTAB, 0,
        0, shstr_off, len(shstr), align=1)

    return bytes(elf)


def main() -> None:
    here = Path(__file__).resolve().parent / "extracted"
    bins = sorted(here.glob("chunk_*.bin"))
    for b in bins:
        load_addr = int(b.stem.split("_")[1], 16)
        out = b.with_suffix(".out")
        out.write_bytes(wrap(b.read_bytes(), load_addr))
        print(f"  {b.name:>40s}  →  {out.name:>40s}  (load=0x{load_addr:08x})")


if __name__ == "__main__":
    main()
