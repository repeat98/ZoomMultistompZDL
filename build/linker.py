"""Custom static linker that turns a TI .obj into a flashable Zoom ZDL.

This is a near-verbatim port of v1's `airwindowsZoom/build/link_zdl.py`,
parameterised so the same code can build any plugin instead of being
hardcoded to ToTape9. Every load-bearing constant carries a comment
explaining the experiment that pinned it down — **do not change them
without hardware proof**.

The linker:
  1. Parses a TI C6000 relocatable ELF (`.obj`).
  2. Lays out a complete ZDL ELF in memory:
       .text  @ 0x00000000   audio func + .text from .obj + divf RTS +
                             NOP_RETURN stub + Dll_<Name> entry
       .const @ 0x80000000   picture + descriptor table + effectTypeImageInfo
       .fardata immediately after .const   KNOB_INFO + plugin's far statics
  3. Resolves all symbol relocations from the .obj.
  4. Synthesises `.dynsym`, `.dynstr`, `.hash`, `.dynamic`, `.rela.dyn`.
  5. Prepends the 76-byte Zoom header.

Usage from a per-plugin build.py:

    from linker import LinkerConfig, Param, link
    cfg = LinkerConfig(
        effect_name="GAIN",
        gid=0x02,                        # Filter category
        fxid=0x0190,
        params=[Param("Level", 100, 50)],
        obj_path="gain/gain.obj",
        output_path="gain/GAIN.ZDL",
    )
    link(cfg)
"""

from __future__ import annotations
import os
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from screen_image import make_text_screen

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _u16(d, o):  return struct.unpack_from('<H', d, o)[0]
def _u32(d, o):  return struct.unpack_from('<I', d, o)[0]
def _i32(d, o):  return struct.unpack_from('<i', d, o)[0]
def _p32(buf, o, v): struct.pack_into('<I', buf, o, v & 0xFFFFFFFF)
def _p16(buf, o, v): struct.pack_into('<H', buf, o, v & 0xFFFF)


def _align_up(val: int, alignment: int) -> int:
    return (val + alignment - 1) & ~(alignment - 1)


def _pad_to(buf: bytearray, size: int, fill: bytes = b'\x00') -> None:
    while len(buf) < size:
        buf.extend(fill)


# ---------------------------------------------------------------------------
# TI C6000 relocation types
# ---------------------------------------------------------------------------
RT_ABS32   = 1
RT_PCR_S21 = 4
RT_ABS_L16 = 9
RT_ABS_H16 = 10

# SBR/DP-relative relocations: B14-relative addressing. The Zoom firmware
# does not initialise B14, so any SBR reloc would dereference garbage and
# freeze the device. Cure: compile with `--mem_model:data=far` so all
# statics use absolute MVKL/MVKH (ABS_L16 + ABS_H16) instead.
# Range covers all SBR_* and SBR_GOT_* variants in the TI C6000 ABI.
RT_SBR_FIRST, RT_SBR_LAST = 11, 23


def _is_sbr_reloc(rtype: int) -> bool:
    return RT_SBR_FIRST <= rtype <= RT_SBR_LAST


# ---------------------------------------------------------------------------
# ELF constants
# ---------------------------------------------------------------------------
ET_DYN     = 3
EM_TI_C6000 = 140
PT_LOAD    = 1
PT_DYNAMIC = 2
SHT_NULL      = 0
SHT_PROGBITS  = 1
SHT_SYMTAB    = 2
SHT_STRTAB    = 3
SHT_RELA      = 4
SHT_HASH      = 5
SHT_DYNAMIC   = 6
SHT_NOBITS    = 8
SHT_DYNSYM    = 11
SHF_WRITE     = 1
SHF_ALLOC     = 2
SHF_EXECINSTR = 4
STB_LOCAL  = 0
STB_GLOBAL = 1
STT_NOTYPE   = 0
STT_OBJECT   = 1
STT_FUNC     = 2
DT_NULL       = 0
DT_PLTRELSZ   = 2
DT_HASH       = 4
DT_STRTAB     = 5
DT_SYMTAB     = 6
DT_RELA       = 7
DT_RELASZ     = 8
DT_RELAENT    = 9
DT_STRSZ      = 10
DT_SYMENT     = 11
DT_SONAME     = 14
DT_PLTREL     = 20
DT_TEXTREL    = 22
DT_JMPREL     = 23
DT_FLAGS      = 30
DT_C6000_GSYM_OFFSET = 0x6000000D
DT_C6000_GSTR_OFFSET = 0x6000000F


# ---------------------------------------------------------------------------
# gid → SONAME prefix table  [v1-empirical, see ABI.md §6.1]
# ---------------------------------------------------------------------------
GID_PREFIX = {
    0x01: "DYN",
    0x02: "FLT",
    0x03: "DRV",
    0x04: "AMP",
    0x05: "CAB",
    0x06: "MOD",
    0x07: "SFX",
    0x08: "DLY",
    0x09: "REV",
    0x0B: "PDL",
}


# ---------------------------------------------------------------------------
# Plugin configuration
# ---------------------------------------------------------------------------

@dataclass
class Param:
    """One user-facing knob descriptor entry."""
    name: str            # ≤ 8 ASCII chars (descriptor slot is 12 but other entries fit in 8)
    max_val: int         # max integer (e.g. 100, 150)
    default_val: int     # initial integer value


@dataclass
class LinkerConfig:
    """Everything plugin-specific the linker needs."""
    effect_name: str                      # ≤ 12 ASCII chars
    gid: int                              # 0x01..0x0B; controls SONAME prefix
    fxid: int                             # uint16 effect ID
    params: list[Param]                   # one entry per knob
    obj_path: str | os.PathLike           # input TI .obj
    output_path: str | os.PathLike        # output GAIN.ZDL etc.

    audio_func_name: Optional[str] = None # default: f"Fx_FLT_{effect_name}"
    fxid_version: bytes = b"1.00"         # 4 bytes
    flags_byte: int = 0x01                # ZDL header byte 0x3D; 0x01 matches majority

    # Optional pre-rendered 128×64 RLE screen image. None → auto-generate
    # a text-only screen showing the effect name.
    screen_image: Optional[bytes] = None

    # Knob xy positions on screen. The firmware paginates by walking the
    # descriptor table and overlaying entries onto these visible slots
    # three-at-a-time, BUT `nknobs` itself must match the parameter count
    # (capped at 3). [v1-empirical was wrong — link_zdl.py hardcoded 3
    # because ToTape9 has 9 params; for fewer params the firmware
    # dereferences nonexistent descriptor entries when interaction
    # starts, which is what froze v2 GAIN at edit time.]
    #
    # Verified against 128 stock MS-70CDR ZDLs:
    #   2 params  → nknobs=2
    #   3+ params → nknobs=3
    #   0 params  → nknobs=0  (OrangeLM)
    # No stock effect uses nknobs=1; whether the firmware accepts it is
    # the next experiment.
    knob_positions: Optional[list[tuple[int, int, int]]] = None

    # Path to extracted __c6xabi_divf RTS code (640 bytes).
    divf_rts_path: Optional[str | os.PathLike] = None

    # Path to LineSel handler blob (384 bytes: onf + edit_a + edit_b + init
    # + __call_stub, copied verbatim from LineSel's .text). The blob
    # provides real edit/onf handlers that read knob values from the host
    # runtime and write into params[5], params[6], params[0]. Without
    # this, NOP_RETURN handlers are used and params[] stays uninitialised.
    # When set, handler_funcs maps logical names to byte offsets within
    # the blob: defaults match LineSel's layout.
    handler_blob_path: Optional[str | os.PathLike] = None
    handler_funcs: dict[str, int] = field(default_factory=lambda: {
        "onf":        0x00,    # OnOff toggle: writes params[0]
        "knob1_edit": 0x60,    # writes params[5] (knob_id=2)
        "knob2_edit": 0xAC,    # writes params[6] (knob_id=3)
        "init":       0xF8,    # has unresolved Coe-table refs; do NOT use
    })

    # Audio-NOP override. When True, the audio function's first 32 bytes
    # are replaced with a canonical B B3 + delay-slot NOP sequence after
    # linking. Useful as a smoke test: lets the firmware exercise the UI
    # without running the plugin's DSP.
    audio_nop: bool = False

    def __post_init__(self) -> None:
        if self.audio_func_name is None:
            self.audio_func_name = f"Fx_FLT_{self.effect_name}"
        if self.gid not in GID_PREFIX:
            raise ValueError(f"unknown gid {self.gid:#x}; add to GID_PREFIX table")

        # Auto-pick knob positions if not given. nknobs must match
        # min(3, len(params)). Defaults follow LineSel (2 knobs) /
        # AIR (3 knobs) layouts.
        n = min(3, len(self.params))
        defaults_by_count = {
            0: [],
            1: [(2, 54, 36)],                          # centered single knob
            2: [(2, 38, 36), (3, 70, 36)],             # LineSel-style spacing
            3: [(2, 14, 34), (3, 38, 34), (4, 62, 34)],
        }
        if self.knob_positions is None:
            self.knob_positions = defaults_by_count[n]
        elif len(self.knob_positions) != n:
            raise ValueError(
                f"knob_positions has {len(self.knob_positions)} entries; "
                f"need {n} (= min(3, n_params))"
            )
        if self.divf_rts_path is None:
            self.divf_rts_path = Path(__file__).resolve().parent / "divf_rts.bin"
        if self.handler_blob_path is None:
            self.handler_blob_path = Path(__file__).resolve().parent / "linesel_handlers.bin"


# ---------------------------------------------------------------------------
# TI .obj parser
# ---------------------------------------------------------------------------

class ObjFile:
    """Parses a TI C6000 relocatable ELF (.obj from cl6x -c)."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.data = Path(path).read_bytes()
        d = self.data
        assert d[:4] == b'\x7fELF', "not an ELF file"
        assert _u16(d, 0x10) == 1, "not ET_REL"

        self.shoff    = _u32(d, 0x20)
        self.shentsz  = _u16(d, 0x2E)
        self.shnum    = _u16(d, 0x30)
        self.shstrndx = _u16(d, 0x32)

        sh = self.shoff + self.shstrndx * self.shentsz
        self.shstrtab = d[_u32(d, sh + 0x10): _u32(d, sh + 0x10) + _u32(d, sh + 0x14)]

        self.sections: list[dict] = []
        for i in range(self.shnum):
            h = self.shoff + i * self.shentsz
            name = self.shstrtab[_u32(d, h):].split(b'\x00')[0].decode('ascii', 'replace')
            sec = {
                'idx': i, 'name': name,
                'type': _u32(d, h + 4), 'flags': _u32(d, h + 8),
                'addr': _u32(d, h + 0xC), 'offset': _u32(d, h + 0x10),
                'size': _u32(d, h + 0x14), 'link': _u32(d, h + 0x18),
                'info': _u32(d, h + 0x1C), 'align': _u32(d, h + 0x20),
                'entsize': _u32(d, h + 0x24),
            }
            if sec['type'] == SHT_NOBITS:
                sec['data'] = bytearray(sec['size'])
            elif sec['size'] > 0:
                sec['data'] = bytearray(d[sec['offset']: sec['offset'] + sec['size']])
            else:
                sec['data'] = bytearray()
            self.sections.append(sec)

        self._load_strtab()
        self._load_symtab()
        self._load_relocs()

    def _load_strtab(self) -> None:
        for s in self.sections:
            if s['name'] == '.symtab' and s['type'] == SHT_SYMTAB:
                self.strtab = self.sections[s['link']]['data']
                return
        raise ValueError("no .strtab")

    def _load_symtab(self) -> None:
        self.symbols: list[dict] = []
        for s in self.sections:
            if s['name'] == '.symtab' and s['type'] == SHT_SYMTAB:
                for i in range(s['size'] // 16):
                    off = i * 16
                    name_idx = struct.unpack_from('<I', s['data'], off)[0]
                    name = self.strtab[name_idx:].split(b'\x00')[0].decode('ascii', 'replace')
                    self.symbols.append({
                        'idx': i, 'name': name,
                        'value': struct.unpack_from('<I', s['data'], off + 4)[0],
                        'size':  struct.unpack_from('<I', s['data'], off + 8)[0],
                        'bind':  s['data'][off + 12] >> 4,
                        'type':  s['data'][off + 12] & 0xf,
                        'shndx': struct.unpack_from('<H', s['data'], off + 14)[0],
                    })
                return
        raise ValueError("no .symtab")

    def _load_relocs(self) -> None:
        self.relocs: dict[int, list[dict]] = {}
        for s in self.sections:
            target_idx = s['info']
            if s['type'] == SHT_RELA:
                entries = []
                for i in range(s['size'] // 12):
                    off = i * 12
                    info = struct.unpack_from('<I', s['data'], off + 4)[0]
                    entries.append({
                        'offset': struct.unpack_from('<I', s['data'], off)[0],
                        'type':   info & 0xFF,
                        'sym_idx': info >> 8,
                        'addend': struct.unpack_from('<i', s['data'], off + 8)[0],
                    })
                self.relocs.setdefault(target_idx, []).extend(entries)

    def get_section(self, name: str) -> Optional[dict]:
        return next((s for s in self.sections if s['name'] == name), None)


# ---------------------------------------------------------------------------
# C6x relocation patchers
# ---------------------------------------------------------------------------

def _patch_abs_l16(code: bytearray, offset: int, value: int) -> None:
    instr = struct.unpack_from('<I', code, offset)[0]
    instr = (instr & ~(0xFFFF << 7)) | ((value & 0xFFFF) << 7)
    struct.pack_into('<I', code, offset, instr)


def _patch_abs_h16(code: bytearray, offset: int, value: int) -> None:
    instr = struct.unpack_from('<I', code, offset)[0]
    instr = (instr & ~(0xFFFF << 7)) | (((value >> 16) & 0xFFFF) << 7)
    struct.pack_into('<I', code, offset, instr)


def _patch_pcr_s21(code: bytearray, offset: int, target_addr: int, instr_addr: int) -> None:
    delta = (target_addr - instr_addr) >> 2          # PC-relative, in instruction words
    if delta < -(1 << 20) or delta >= (1 << 20):
        raise ValueError(f"PCR_S21 displacement {delta:#x} out of range")
    instr = struct.unpack_from('<I', code, offset)[0]
    instr = (instr & ~(0x1FFFFF << 7)) | ((delta & 0x1FFFFF) << 7)
    struct.pack_into('<I', code, offset, instr)


# ---------------------------------------------------------------------------
# String table builder
# ---------------------------------------------------------------------------

class _StringTable:
    def __init__(self) -> None:
        self.data = bytearray(b'\x00')
        self.offsets: dict[str, int] = {'': 0}

    def add(self, s: str) -> int:
        if s in self.offsets:
            return self.offsets[s]
        off = len(self.data)
        self.data.extend(s.encode('ascii') + b'\x00')
        self.offsets[s] = off
        return off

    def get_bytes(self) -> bytes:
        return bytes(self.data)


def _elf_hash(name: str) -> int:
    h = 0
    for ch in name.encode('ascii'):
        h = (h << 4) + ch
        g = h & 0xF0000000
        if g:
            h ^= g >> 24
        h &= ~g & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------------------
# Descriptor table builder  [v1-empirical, see ABI.md §3]
# ---------------------------------------------------------------------------

def _build_descriptor(
    effect_name: str,
    audio_func_va: int,
    init_func_va: int,
    onf_func_va: int,
    knob_edit_vas: list[int],
    params: list[Param],
) -> tuple[bytes, list[tuple[int, int]]]:
    """Returns (descriptor_bytes, [(offset_in_desc, target_va), ...])."""
    assert len(knob_edit_vas) == len(params), (
        f"need one edit handler VA per param ({len(params)}); "
        f"got {len(knob_edit_vas)}"
    )
    desc = bytearray()
    relocs: list[tuple[int, int]] = []

    # Entry 0: OnOff
    entry = bytearray(0x30)
    entry[0:6] = b'OnOff\x00'
    _p32(entry, 0x0C, 1)
    _p32(entry, 0x1C, onf_func_va)
    relocs.append((len(desc) + 0x1C, onf_func_va))
    desc.extend(entry)

    # Entry 1: Effect-name self-entry
    entry = bytearray(0x30)
    name_bytes = effect_name.encode('ascii')[:12]
    entry[:len(name_bytes)] = name_bytes
    _p32(entry, 0x0C, 0xFFFFFFFF)
    _p32(entry, 0x14, 1)
    _p32(entry, 0x1C, init_func_va)
    _p32(entry, 0x20, audio_func_va)
    relocs.append((len(desc) + 0x1C, init_func_va))
    relocs.append((len(desc) + 0x20, audio_func_va))
    desc.extend(entry)

    last_idx = len(params) - 1
    for i, p in enumerate(params):
        entry = bytearray(0x30)
        nb = p.name.encode('ascii')[:8]
        entry[:len(nb)] = nb
        _p32(entry, 0x0C, p.max_val)
        _p32(entry, 0x10, p.default_val)
        _p32(entry, 0x1C, knob_edit_vas[i])
        if i == last_idx:
            _p32(entry, 0x2C, 0x04)
        relocs.append((len(desc) + 0x1C, knob_edit_vas[i]))
        desc.extend(entry)

    return bytes(desc), relocs


# ---------------------------------------------------------------------------
# effectTypeImageInfo — exactly 212 bytes, exactly 3 knob slots [v1-empirical]
# ---------------------------------------------------------------------------

def _build_image_info(
    pic_va: int,
    knob_info_va: int,
    knob_positions: list[tuple[int, int, int]],
) -> tuple[bytes, list[tuple[int, int]]]:
    info = bytearray()
    relocs: list[tuple[int, int]] = []

    info.extend(struct.pack('<I', 0))
    info.extend(struct.pack('<I', 1))
    info.extend(struct.pack('<I', 0))
    info.extend(struct.pack('<I', 128))     # screen width
    info.extend(struct.pack('<I', 64))      # screen height
    relocs.append((len(info), pic_va))
    info.extend(struct.pack('<I', pic_va))
    # +0x18 / +0x1C are picture-related per-effect values (vary across
    # 128 stock ZDLs without obvious meaning — possibly clip extents).
    # We match LineSel exactly (the stock 2-knob gid=0x02 effect that
    # is closest to our common test case). The values aren't load-bearing
    # for boot — GAIN's picture rendered fine with (28, 25) — but
    # matching stock keeps the diff surface small.
    info.extend(struct.pack('<I', 28))
    info.extend(struct.pack('<I', 17))

    info.extend(struct.pack('<I', len(knob_positions)))
    for kid, kx, ky in knob_positions:
        info.extend(struct.pack('<I', kid))
        info.extend(struct.pack('<I', kx))
        info.extend(struct.pack('<I', ky))
        relocs.append((len(info), knob_info_va))
        info.extend(struct.pack('<I', knob_info_va))

    if len(info) > 212:
        raise ValueError(f"effectTypeImageInfo is {len(info)} > 212 bytes")
    while len(info) < 212:
        info.append(0)
    return bytes(info), relocs


# KNOB_INFO {20, 15, 11, 0, 2, 0}: 24 bytes in .fardata. field4=2 ships in
# all 128 stock MS-70CDR ZDLs; v1 tried field4=5 once and the unit froze
# at FX-select time. Don't change.
_KNOB_INFO = struct.pack('<6I', 20, 15, 11, 0, 2, 0)


# ---------------------------------------------------------------------------
# NOP_RETURN — 32-byte stub used as init/onf/edit handler
# ---------------------------------------------------------------------------

_NOP_RETURN = bytes([
    0x62, 0x03, 0x0C, 0x00,  # B B3
    0x00, 0x80, 0x00, 0x00,  # multi-cycle NOP (delay slot 1)
    0x00, 0x00, 0x00, 0x00,  # NOP 1 (delay slot 2)
    0x00, 0x00, 0x00, 0x00,  # NOP 1 (delay slot 3)
    0x00, 0x00, 0x00, 0x00,  # NOP 1 (delay slot 4)
    0x00, 0x00, 0x00, 0x00,  # NOP 1 (delay slot 5)
    0x00, 0x00, 0x00, 0x00,  # NOP 1
    0x00, 0x00, 0x00, 0x00,  # NOP 1
])


# ---------------------------------------------------------------------------
# Dll_<Name> entry function  [v1-empirical]
#
# Verbatim 200-byte copy of NoiseGate's Dll function with 4 reloc points
# repatched to point at our descriptor table + effectTypeImageInfo.
#
# An earlier 32-byte attempt patterned after LOFIDLY's Dll caused
# inconsistent FX-select freezes. NoiseGate boots cleanly. Why this body
# specifically works isn't understood — leave it alone.
# ---------------------------------------------------------------------------

_DLL_WORDS = [
    0x842621EF,
    0x0001AC2A,  # +0x04: MVK.S2  lo(desc), B0    ← ABS_L16 reloc
    0x0080DC29,  # +0x08: MVK.S1  lo(info), A1    ← ABS_L16 reloc
    0x0040006B,  # +0x0C: MVKH.S2 hi(desc), B0    ← ABS_H16 reloc
    0x30040204,
    0x00C00068,  # +0x14: MVKH.S1 hi(info), A1    ← ABS_H16 reloc
    0x00904274, 0xE2200202, 0x00903D5B, 0x00903D59, 0x19760032, 0x00909BF9,
    0x00043D73, 0x51002040, 0x02100CE3, 0xE0800010, 0x40002943, 0x030018F0,
    0x011099FB, 0xC5621836, 0x00000C12, 0x4100A35B, 0x608808F3, 0xE10000C0,
    0x610829A1, 0x00000812, 0x621029A3, 0x52109B31, 0x00000810, 0x521029A3,
    0x62109B31, 0x0100E8DB, 0x0080E9C3, 0x00000410, 0x6080A35B, 0x22109979,
    0x200029C3, 0x00000413, 0x00000001, 0x00000000, 0x22109979, 0x200029C3,
    0x4087E05B, 0x40000012,
    0x000C0362,  # +0xB0: B B3 (canonical return)
    0x92100CE1, 0x8200A358, 0x921009E0, 0x92104840, 0x00002000,
]
_DLL_RELA_OFFSETS = [
    (0x04, RT_ABS_L16, 'desc'),
    (0x08, RT_ABS_L16, 'info'),
    (0x0C, RT_ABS_H16, 'desc'),
    (0x14, RT_ABS_H16, 'info'),
]


def _build_dll() -> bytes:
    code = bytearray()
    for w in _DLL_WORDS:
        code.extend(struct.pack('<I', w))
    assert len(code) == 200
    return bytes(code)


# ---------------------------------------------------------------------------
# Main link entry point
# ---------------------------------------------------------------------------

def link(cfg: LinkerConfig) -> None:
    """Build cfg.output_path from cfg.obj_path."""
    print(f"=== {cfg.effect_name} ZDL Linker ===")

    # ----- Parse .obj -----
    obj = ObjFile(cfg.obj_path)
    audio_sec = obj.get_section('.audio')
    text_sec  = obj.get_section('.text')
    fardata_sec = obj.get_section('.fardata')

    if audio_sec is None or audio_sec['size'] == 0:
        raise SystemExit(
            "no .audio section in .obj — did you forget "
            "`#pragma CODE_SECTION(Fx_FLT_<Name>, \".audio\")`?"
        )

    print(f"  .audio:   {audio_sec['size']} bytes")
    print(f"  .text:    {text_sec['size'] if text_sec else 0} bytes")
    print(f"  .fardata: {fardata_sec['size'] if fardata_sec else 0} bytes")

    externals = {sym['name'] for sym in obj.symbols if sym['shndx'] == 0 and sym['name']}
    if externals:
        print(f"  external symbols: {externals}")

    # ----- Load divf RTS -----
    divf_code = Path(cfg.divf_rts_path).read_bytes()

    # ----- Load handler blob (or fall back to NOP_RETURN handlers) -----
    handler_blob = b""
    handler_va: dict[str, int] = {}                              # filled below
    handler_path = Path(cfg.handler_blob_path) if cfg.handler_blob_path else None
    use_real_handlers = handler_path is not None and handler_path.exists()
    if use_real_handlers:
        handler_blob = handler_path.read_bytes()
        print(f"  handlers: {handler_path.name} ({len(handler_blob)} bytes)")

    # ----- Screen image -----
    pic_data = bytearray(cfg.screen_image or make_text_screen(cfg.effect_name))
    while len(pic_data) % 4:
        pic_data.append(0)
    pic_end = len(pic_data)

    # ----- Collect .far BSS sections -----
    far_sections: list[dict] = []
    far_total = 0
    fardata_size = fardata_sec['size'] if fardata_sec else 0
    for s in obj.sections:
        if (s['name'] == '.far' or s['name'].startswith('.far:')) and s['type'] == SHT_NOBITS:
            aligned = _align_up(far_total, max(s['align'], 1))
            s['_data_offset'] = fardata_size + aligned
            far_sections.append(s)
            far_total = aligned + s['size']
    far_total = _align_up(far_total, 8)
    our_data_size = fardata_size + far_total
    if far_sections:
        print(f"  .far BSS: {far_total} bytes ({len(far_sections)} sections)")

    # =====================================================================
    # Memory layout
    # =====================================================================
    TEXT_VA  = 0x00000000
    CONST_VA = 0x80000000

    AUDIO_OFF       = 0x0000
    AUDIO_PAD       = _align_up(audio_sec['size'], 32)
    TEXT_ORIG_OFF   = AUDIO_PAD
    TEXT_ORIG_SIZE  = text_sec['size'] if text_sec else 0
    HANDLER_OFF     = _align_up(TEXT_ORIG_OFF + TEXT_ORIG_SIZE, 32)
    HANDLER_SIZE    = len(handler_blob)
    DIVF_OFF        = _align_up(HANDLER_OFF + HANDLER_SIZE, 32)
    DIVF_SIZE       = len(divf_code)
    NOP_RET_OFF     = _align_up(DIVF_OFF + DIVF_SIZE, 32)
    NOP_RET_SIZE    = 32
    DLL_OFF         = NOP_RET_OFF + NOP_RET_SIZE
    DLL_SIZE        = 200
    TEXT_TOTAL      = _align_up(DLL_OFF + DLL_SIZE, 32)

    print(f"\n  .text layout:")
    print(f"    audio    @ 0x{AUDIO_OFF:04X}  ({audio_sec['size']} → padded {AUDIO_PAD})")
    print(f"    text     @ 0x{TEXT_ORIG_OFF:04X}  ({TEXT_ORIG_SIZE})")
    if HANDLER_SIZE:
        print(f"    handlers @ 0x{HANDLER_OFF:04X}  ({HANDLER_SIZE})")
    print(f"    divf     @ 0x{DIVF_OFF:04X}  ({DIVF_SIZE})")
    print(f"    nop_ret  @ 0x{NOP_RET_OFF:04X}")
    print(f"    Dll      @ 0x{DLL_OFF:04X}")
    print(f"    total      0x{TEXT_TOTAL:X}")

    # ----- Build .text -----
    out_text = bytearray(TEXT_TOTAL)
    out_text[AUDIO_OFF:AUDIO_OFF + audio_sec['size']] = audio_sec['data']
    if text_sec and TEXT_ORIG_SIZE:
        out_text[TEXT_ORIG_OFF:TEXT_ORIG_OFF + TEXT_ORIG_SIZE] = text_sec['data']
    if HANDLER_SIZE:
        out_text[HANDLER_OFF:HANDLER_OFF + HANDLER_SIZE] = handler_blob
    out_text[DIVF_OFF:DIVF_OFF + DIVF_SIZE] = divf_code
    out_text[NOP_RET_OFF:NOP_RET_OFF + NOP_RET_SIZE] = _NOP_RETURN
    out_text[DLL_OFF:DLL_OFF + DLL_SIZE] = _build_dll()

    # Resolve handler VAs (one per logical name)
    if use_real_handlers:
        for name, off in cfg.handler_funcs.items():
            handler_va[name] = TEXT_VA + HANDLER_OFF + off

    # ----- Map .obj sections to VAs -----
    section_va: dict[int, int] = {
        audio_sec['idx']: TEXT_VA + AUDIO_OFF,
    }
    if text_sec:
        section_va[text_sec['idx']] = TEXT_VA + TEXT_ORIG_OFF

    # =====================================================================
    # Build .const layout
    # =====================================================================
    const_data = bytearray(pic_data)

    DESC_OFF_IN_CONST = _align_up(len(const_data), 4)
    _pad_to(const_data, DESC_OFF_IN_CONST)

    NOP_VA = TEXT_VA + NOP_RET_OFF
    onf_va  = handler_va.get("onf",  NOP_VA)
    # init has unresolved Coe-table refs in LineSel's blob; always NOP it.
    # If/when we extract a self-contained init, swap this to handler_va["init"].
    init_va = NOP_VA

    # Per-knob edit handlers. With LineSel's blob:
    #   knob 1 → params[5] via knob1_edit
    #   knob 2 → params[6] via knob2_edit
    # >2 knobs need additional edit handlers (not yet extracted).
    edit_keys = ["knob1_edit", "knob2_edit"]
    knob_edit_vas: list[int] = []
    for i, _ in enumerate(cfg.params):
        key = edit_keys[i] if i < len(edit_keys) else None
        knob_edit_vas.append(handler_va.get(key, NOP_VA) if key else NOP_VA)

    desc_bytes, desc_relocs = _build_descriptor(
        effect_name=cfg.effect_name,
        audio_func_va=TEXT_VA + AUDIO_OFF,
        init_func_va=init_va,
        onf_func_va=onf_va,
        knob_edit_vas=knob_edit_vas,
        params=cfg.params,
    )
    expected = 0x30 * (2 + len(cfg.params))
    assert len(desc_bytes) == expected, \
        f"descriptor size {len(desc_bytes)} != {expected}"

    DESC_VA = CONST_VA + DESC_OFF_IN_CONST
    PIC_VA  = CONST_VA + 0
    const_data.extend(desc_bytes)

    INFO_OFF_IN_CONST = _align_up(len(const_data), 4)
    _pad_to(const_data, INFO_OFF_IN_CONST)
    INFO_VA = CONST_VA + INFO_OFF_IN_CONST

    # First pass: estimate const size to compute KNOB_INFO_VA, then rebuild
    # imageInfo with the confirmed VA. (imageInfo is always 212 bytes so the
    # second pass produces the same result; the indirection is just to
    # decouple the two builds cleanly.)
    info_pass1, _ = _build_image_info(
        pic_va=PIC_VA,
        knob_info_va=CONST_VA + _align_up(INFO_OFF_IN_CONST + 212, 8),
        knob_positions=cfg.knob_positions,
    )
    const_data.extend(info_pass1)
    CONST_SIZE = _align_up(len(const_data), 8)
    _pad_to(const_data, CONST_SIZE)

    FARDATA_VA   = CONST_VA + CONST_SIZE
    KNOB_INFO_VA = FARDATA_VA
    OUR_FARDATA_VA = FARDATA_VA + len(_KNOB_INFO)

    # Second pass: rebuild imageInfo with the actual KNOB_INFO_VA.
    const_data = bytearray(const_data[:INFO_OFF_IN_CONST])
    info_bytes, info_relocs = _build_image_info(
        pic_va=PIC_VA,
        knob_info_va=KNOB_INFO_VA,
        knob_positions=cfg.knob_positions,
    )
    const_data.extend(info_bytes)
    CONST_SIZE = _align_up(len(const_data), 8)
    _pad_to(const_data, CONST_SIZE)
    FARDATA_VA   = CONST_VA + CONST_SIZE
    KNOB_INFO_VA = FARDATA_VA
    OUR_FARDATA_VA = FARDATA_VA + len(_KNOB_INFO)

    print(f"\n  .const layout:")
    print(f"    picture    @ 0x{0:04X}  ({pic_end})")
    print(f"    descriptor @ 0x{DESC_OFF_IN_CONST:04X}  ({len(desc_bytes)})")
    print(f"    imageInfo  @ 0x{INFO_OFF_IN_CONST:04X}  ({len(info_bytes)})")
    print(f"    total        0x{CONST_SIZE:X}")
    print(f"    .const VA    0x{CONST_VA:08X}")
    print(f"    .fardata VA  0x{FARDATA_VA:08X}")

    # ----- Map .fardata sections -----
    if fardata_sec:
        section_va[fardata_sec['idx']] = OUR_FARDATA_VA
    for s in far_sections:
        section_va[s['idx']] = OUR_FARDATA_VA + s['_data_offset']

    # ----- Build .fardata -----
    total_fardata_seg = _align_up(len(_KNOB_INFO) + our_data_size, 4)
    fardata_data = bytearray(total_fardata_seg)
    fardata_data[:len(_KNOB_INFO)] = _KNOB_INFO
    if fardata_sec and fardata_sec['size'] > 0:
        off = len(_KNOB_INFO)
        fardata_data[off:off + fardata_sec['size']] = fardata_sec['data']

    # =====================================================================
    # Resolve .obj symbols → VAs
    # =====================================================================
    sym_addr: dict[int, int] = {}
    undefined: dict[str, int] = {}
    for sym in obj.symbols:
        if sym['shndx'] == 0:
            if sym['name']:
                undefined[sym['name']] = sym['idx']
        elif sym['shndx'] < 0xFF00 and sym['shndx'] in section_va:
            sym_addr[sym['idx']] = section_va[sym['shndx']] + sym['value']

    if '__c6xabi_divf' in undefined:
        sym_addr[undefined['__c6xabi_divf']] = TEXT_VA + DIVF_OFF

    for name, idx in undefined.items():
        if idx not in sym_addr:
            print(f"  WARNING: unresolved external: {name}")

    # =====================================================================
    # Apply .text/.audio relocations
    # =====================================================================
    dyn_relocs: list[tuple[int, int, int]] = []   # (va, type, target_va)

    def _apply_relocs(sec, base_off):
        n_ok = 0
        for rel in obj.relocs.get(sec['idx'], []):
            sym = obj.symbols[rel['sym_idx']]
            offset = rel['offset']
            rtype = rel['type']
            if _is_sbr_reloc(rtype):
                raise RuntimeError(
                    f"{sec['name']} reloc type {rtype} is SBR/B14-relative at "
                    f"+0x{offset:X} (sym={sym['name']!r}). Compile with "
                    f"--mem_model:data=far."
                )
            if rel['sym_idx'] not in sym_addr:
                print(f"  SKIP unresolved sym {sym['name']!r} at {sec['name']}+0x{offset:X}")
                continue
            target = sym_addr[rel['sym_idx']] + rel['addend']
            file_off = base_off + offset
            if rtype == RT_ABS_L16:
                _patch_abs_l16(out_text, file_off, target)
            elif rtype == RT_ABS_H16:
                _patch_abs_h16(out_text, file_off, target)
            elif rtype == RT_PCR_S21:
                _patch_pcr_s21(out_text, file_off, target, TEXT_VA + file_off)
            else:
                print(f"  SKIP unknown reloc type {rtype} at {sec['name']}+0x{offset:X}")
                continue
            n_ok += 1
        return n_ok

    n_relocs = _apply_relocs(audio_sec, AUDIO_OFF)
    if text_sec and text_sec.get('size'):
        n_relocs += _apply_relocs(text_sec, TEXT_ORIG_OFF)
    print(f"\n  Applied {n_relocs} .obj relocations")

    # ----- Patch Dll function MVK/MVKH -----
    DESC_TABLE_VA = DESC_VA
    for off_in_dll, rtype, purpose in _DLL_RELA_OFFSETS:
        file_off = DLL_OFF + off_in_dll
        target = DESC_TABLE_VA if purpose == 'desc' else INFO_VA
        if rtype == RT_ABS_L16:
            _patch_abs_l16(out_text, file_off, target)
        else:
            _patch_abs_h16(out_text, file_off, target)
        dyn_relocs.append((TEXT_VA + file_off, rtype, target))

    # =====================================================================
    # Build .rela.dyn
    # =====================================================================
    all_rela: list[tuple[int, int, int]] = list(dyn_relocs)
    for off_in_desc, func_va in desc_relocs:
        all_rela.append((DESC_VA + off_in_desc, RT_ABS32, func_va))
    for off_in_info, ptr_va in info_relocs:
        all_rela.append((INFO_VA + off_in_info, RT_ABS32, ptr_va))

    # Each unique target VA gets one dynsym entry.
    dynsym_targets: dict[int, int] = {tgt: 0 for _, _, tgt in all_rela}

    # =====================================================================
    # Build .dynsym / .dynstr
    # =====================================================================
    dynstr = _StringTable()
    dynsym_list: list[dict] = [{
        'name': '', 'name_idx': 0, 'value': 0, 'size': 0,
        'info': 0, 'shndx': 0,
    }]

    name_for_va = {
        TEXT_VA + AUDIO_OFF: cfg.audio_func_name,
        TEXT_VA + NOP_RET_OFF: 'nop_return',
        PIC_VA: f'picEffectType_{cfg.effect_name}',
        DESC_TABLE_VA: cfg.effect_name,
        INFO_VA: 'effectTypeImageInfo',
        KNOB_INFO_VA: '_infoEffectTypeKnob_A_2',
    }
    if fardata_sec:
        for sym in obj.symbols:
            if sym['shndx'] in section_va:
                va = section_va[sym['shndx']] + sym['value']
                if va >= 0x80000000 and sym['name']:
                    name_for_va.setdefault(va, sym['name'])

    size_for_va = {
        DESC_TABLE_VA: len(desc_bytes),
        INFO_VA:       len(info_bytes),
        PIC_VA:        pic_end,
        KNOB_INFO_VA:  len(_KNOB_INFO),
    }

    def _shndx(va: int) -> int:
        # Section indices in our output ELF (must match write_shdr below):
        # 4 = .text, 5 = .const, 6 = .fardata
        if va < 0x80000000:
            return 4
        elif va >= FARDATA_VA:
            return 6
        else:
            return 5

    for tgt in sorted(dynsym_targets):
        name = name_for_va.get(tgt, f'_sym_0x{tgt:08X}')
        idx = len(dynsym_list)
        dynsym_targets[tgt] = idx
        stype = STT_FUNC if tgt < 0x80000000 else STT_OBJECT
        dynsym_list.append({
            'name': name, 'name_idx': dynstr.add(name),
            'value': tgt, 'size': size_for_va.get(tgt, 0),
            'info': (STB_LOCAL << 4) | stype,
            'shndx': _shndx(tgt),
        })

    # The Dll_<Name> global symbol is the one the loader hooks in by name.
    dll_name = f'Dll_{cfg.effect_name}'
    dll_name_idx = dynstr.add(dll_name)
    dll_sym_idx = len(dynsym_list)
    dynsym_list.append({
        'name': dll_name, 'name_idx': dll_name_idx,
        'value': TEXT_VA + DLL_OFF, 'size': 0,
        'info': (STB_GLOBAL << 4) | STT_FUNC,
        'shndx': 4,
    })

    # Profiling/static-base symbols seen in every stock ZDL.
    SHN_ABS = 0xFFF1
    for sn in ('__TI_STATIC_BASE', '__TI_pprof_out_hndl',
               '__TI_prof_data_start', '__TI_prof_data_size'):
        ni = dynstr.add(sn)
        val = 0xFFFFFFFF if 'pprof' in sn or 'prof_data' in sn else 0
        shndx = SHN_ABS if val == 0xFFFFFFFF else 0
        dynsym_list.append({
            'name': sn, 'name_idx': ni,
            'value': val, 'size': 0,
            'info': (STB_LOCAL << 4) | STT_NOTYPE,
            'shndx': shndx,
        })

    # SONAME — must follow `ZDL_<GID_PREFIX>_<Name>.out` or the firmware
    # falls back to a 2-knob no-page mode.
    soname = f'ZDL_{GID_PREFIX[cfg.gid]}_{cfg.effect_name}.out'
    soname_idx = dynstr.add(soname)

    # ----- Pack dynamic structures -----
    rela_dyn_data = bytearray()
    for va, rtype, tgt in all_rela:
        sym_idx = dynsym_targets[tgt]
        rela_dyn_data.extend(struct.pack('<Iii', va, (sym_idx << 8) | rtype, 0))

    dynsym_data = bytearray()
    for s in dynsym_list:
        dynsym_data.extend(struct.pack('<III', s['name_idx'], s['value'], s['size']))
        dynsym_data.append(s['info'])
        dynsym_data.append(0)                                    # st_other
        dynsym_data.extend(struct.pack('<H', s['shndx']))

    nbuckets = max(len(dynsym_list), 17)
    nchains = len(dynsym_list)
    buckets = [0] * nbuckets
    chains  = [0] * nchains
    for i in range(1, len(dynsym_list)):
        h = _elf_hash(dynsym_list[i]['name']) % nbuckets
        chains[i] = buckets[h]
        buckets[h] = i
    hash_data = bytearray()
    hash_data.extend(struct.pack('<II', nbuckets, nchains))
    for b in buckets: hash_data.extend(struct.pack('<I', b))
    for c in chains:  hash_data.extend(struct.pack('<I', c))

    dynstr_data = dynstr.get_bytes()

    print(f"\n  .dynsym: {len(dynsym_list)} symbols  ({len(dynsym_data)} bytes)")
    print(f"  .dynstr: {len(dynstr_data)} bytes")
    print(f"  .hash:   {len(hash_data)} bytes")
    print(f"  .rela.dyn: {len(all_rela)} entries  ({len(rela_dyn_data)} bytes)")

    # =====================================================================
    # Lay out the ELF file
    # =====================================================================
    ELF_HDR_SIZE = 0x34
    PHDR_SIZE    = 0x20
    NUM_PHDRS    = 4
    PHDR_TABLE   = NUM_PHDRS * PHDR_SIZE

    cur = ELF_HDR_SIZE + PHDR_TABLE
    text_file_off = _align_up(cur, 32);                cur = text_file_off + TEXT_TOTAL
    const_file_off = _align_up(cur, 8);                cur = const_file_off + CONST_SIZE
    # .fardata: only KNOB_INFO ships in the file. memsz==filesz; no BSS.
    # [v1-empirical: memsz>filesz overflows into firmware param memory,
    # corrupts paging.]
    fardata_file_off = _align_up(cur, 4);              cur = fardata_file_off + len(_KNOB_INFO)
    rela_dyn_file_off = _align_up(cur, 4);             cur = rela_dyn_file_off + len(rela_dyn_data)
    rela_plt_file_off = cur                            # empty
    dynamic_size = 21 * 8                              # match Exciter
    dynamic_file_off = _align_up(cur, 4);              cur = dynamic_file_off + dynamic_size
    dynsym_file_off = _align_up(cur, 4);               cur = dynsym_file_off + len(dynsym_data)
    dynstr_file_off = _align_up(cur, 4);               cur = dynstr_file_off + len(dynstr_data)
    hash_file_off = _align_up(cur, 4);                 cur = hash_file_off + len(hash_data)

    shstr = _StringTable()
    shstr_names = ['', '.rela.dyn', '.rela.plt', '.audio', '.text',
                   '.const', '.fardata', '.dynamic', '.dynsym', '.dynstr',
                   '.hash', '.shstrtab']
    shname_idx = {n: shstr.add(n) for n in shstr_names}
    shstr_data = shstr.get_bytes()
    shstrtab_file_off = _align_up(cur, 4);             cur = shstrtab_file_off + len(shstr_data)

    NUM_SECTIONS = 12
    SHDR_SIZE    = 0x28
    shdr_file_off = _align_up(cur, 4);                 cur = shdr_file_off + NUM_SECTIONS * SHDR_SIZE
    elf_size = cur

    # ----- ZDL header (76 bytes) -----
    zdl_hdr = bytearray(76)
    zdl_hdr[4:8] = b'SIZE'
    struct.pack_into('<I', zdl_hdr,  8, 8)
    struct.pack_into('<I', zdl_hdr, 12, 0x38)
    struct.pack_into('<I', zdl_hdr, 16, elf_size)
    zdl_hdr[20:24] = b'INFO'
    struct.pack_into('<I', zdl_hdr, 24, 0x30)
    zdl_hdr[28:60] = b'ZOOM EFFECT DLL SYSTEM VER 1.00\x00'
    zdl_hdr[60] = cfg.gid
    zdl_hdr[61] = cfg.flags_byte
    struct.pack_into('<H', zdl_hdr, 64, cfg.fxid & 0xFFFF)
    zdl_hdr[67] = cfg.gid                                       # gid duplicate
    zdl_hdr[68:72] = cfg.fxid_version[:4].ljust(4, b'\x00')

    # ----- .dynamic -----
    dyn = bytearray()
    def _de(tag, val):
        dyn.extend(struct.pack('<II', tag, val))
    gsym_offset = dll_sym_idx * 16
    gstr_offset = dll_name_idx
    _de(DT_PLTRELSZ, 0)
    _de(DT_HASH, hash_file_off)
    _de(DT_STRTAB, dynstr_file_off)
    _de(DT_SYMTAB, dynsym_file_off)
    _de(DT_RELA, rela_dyn_file_off)
    _de(DT_RELASZ, len(rela_dyn_data))
    _de(DT_RELAENT, 12)
    _de(DT_STRSZ, len(dynstr_data))
    _de(DT_SYMENT, 16)
    _de(DT_SONAME, soname_idx)
    _de(DT_PLTREL, 7)                                           # = DT_RELA
    _de(DT_TEXTREL, 0)
    _de(DT_JMPREL, rela_plt_file_off)
    _de(DT_FLAGS, 4)                                            # DF_TEXTREL
    _de(DT_C6000_GSYM_OFFSET, gsym_offset)
    _de(DT_C6000_GSTR_OFFSET, gstr_offset)
    while len(dyn) < dynamic_size:
        _de(DT_NULL, 0)

    # ----- Assemble ELF -----
    elf = bytearray(elf_size)
    elf[0:4] = b'\x7fELF'
    elf[4] = 1                                                  # ELFCLASS32
    elf[5] = 1                                                  # ELFDATA2LSB
    elf[6] = 1                                                  # EV_CURRENT
    elf[7] = 0x40                                               # ELFOSABI_C6000_EABI
    _p16(elf, 0x10, ET_DYN)
    _p16(elf, 0x12, EM_TI_C6000)
    _p32(elf, 0x14, 1)
    _p32(elf, 0x18, TEXT_VA + DLL_OFF)                          # e_entry
    _p32(elf, 0x1C, ELF_HDR_SIZE)                               # e_phoff
    _p32(elf, 0x20, shdr_file_off)                              # e_shoff
    _p32(elf, 0x24, 0)
    _p16(elf, 0x28, ELF_HDR_SIZE)
    _p16(elf, 0x2A, PHDR_SIZE)
    _p16(elf, 0x2C, NUM_PHDRS)
    _p16(elf, 0x2E, SHDR_SIZE)
    _p16(elf, 0x30, NUM_SECTIONS)
    _p16(elf, 0x32, NUM_SECTIONS - 1)                           # e_shstrndx

    p = ELF_HDR_SIZE
    # PT_LOAD .text r-x
    _p32(elf, p+0x00, PT_LOAD); _p32(elf, p+0x04, text_file_off)
    _p32(elf, p+0x08, TEXT_VA); _p32(elf, p+0x0C, TEXT_VA)
    _p32(elf, p+0x10, TEXT_TOTAL); _p32(elf, p+0x14, TEXT_TOTAL)
    _p32(elf, p+0x18, 5); _p32(elf, p+0x1C, 32)
    p += PHDR_SIZE
    # PT_LOAD .const r--
    _p32(elf, p+0x00, PT_LOAD); _p32(elf, p+0x04, const_file_off)
    _p32(elf, p+0x08, CONST_VA); _p32(elf, p+0x0C, CONST_VA)
    _p32(elf, p+0x10, CONST_SIZE); _p32(elf, p+0x14, CONST_SIZE)
    _p32(elf, p+0x18, 4); _p32(elf, p+0x1C, 8)
    p += PHDR_SIZE
    # PT_LOAD .fardata rw-, memsz == filesz, no BSS  [v1-empirical]
    _p32(elf, p+0x00, PT_LOAD); _p32(elf, p+0x04, fardata_file_off)
    _p32(elf, p+0x08, FARDATA_VA); _p32(elf, p+0x0C, FARDATA_VA)
    _p32(elf, p+0x10, len(_KNOB_INFO)); _p32(elf, p+0x14, len(_KNOB_INFO))
    _p32(elf, p+0x18, 6); _p32(elf, p+0x1C, 4)
    p += PHDR_SIZE
    # PT_DYNAMIC
    _p32(elf, p+0x00, PT_DYNAMIC); _p32(elf, p+0x04, dynamic_file_off)
    _p32(elf, p+0x08, 0); _p32(elf, p+0x0C, 0)
    _p32(elf, p+0x10, dynamic_size); _p32(elf, p+0x14, 0)
    _p32(elf, p+0x18, 6); _p32(elf, p+0x1C, 0)

    # ----- Section data -----
    elf[text_file_off:text_file_off + TEXT_TOTAL]              = out_text
    elf[const_file_off:const_file_off + CONST_SIZE]            = const_data
    elf[fardata_file_off:fardata_file_off + len(_KNOB_INFO)]   = fardata_data[:len(_KNOB_INFO)]
    elf[rela_dyn_file_off:rela_dyn_file_off + len(rela_dyn_data)] = rela_dyn_data
    elf[dynamic_file_off:dynamic_file_off + len(dyn)]          = dyn
    elf[dynsym_file_off:dynsym_file_off + len(dynsym_data)]    = dynsym_data
    elf[dynstr_file_off:dynstr_file_off + len(dynstr_data)]    = dynstr_data
    elf[hash_file_off:hash_file_off + len(hash_data)]          = hash_data
    elf[shstrtab_file_off:shstrtab_file_off + len(shstr_data)] = shstr_data

    # ----- Section headers -----
    def _sh(idx, name, sh_type, flags, addr, offset, size,
            link=0, info=0, align=0, entsize=0):
        o = shdr_file_off + idx * SHDR_SIZE
        _p32(elf, o + 0x00, shname_idx.get(name, 0))
        _p32(elf, o + 0x04, sh_type)
        _p32(elf, o + 0x08, flags)
        _p32(elf, o + 0x0C, addr)
        _p32(elf, o + 0x10, offset)
        _p32(elf, o + 0x14, size)
        _p32(elf, o + 0x18, link)
        _p32(elf, o + 0x1C, info)
        _p32(elf, o + 0x20, align)
        _p32(elf, o + 0x24, entsize)

    _sh(0, '', SHT_NULL, 0, 0, 0, 0)
    _sh(1, '.rela.dyn', SHT_RELA, 0, 0, rela_dyn_file_off, len(rela_dyn_data),
        link=8, info=0, entsize=12)
    _sh(2, '.rela.plt', SHT_RELA, 0, 0, rela_plt_file_off, 0,
        link=8, info=0, entsize=12)
    _sh(3, '.audio', SHT_PROGBITS, 0, 0, 0, 0, align=1)
    _sh(4, '.text',  SHT_PROGBITS, SHF_ALLOC | SHF_EXECINSTR,
        TEXT_VA, text_file_off, TEXT_TOTAL, align=32)
    _sh(5, '.const', SHT_PROGBITS, SHF_ALLOC,
        CONST_VA, const_file_off, CONST_SIZE, align=8)
    _sh(6, '.fardata', SHT_PROGBITS, SHF_ALLOC | SHF_WRITE,
        FARDATA_VA, fardata_file_off, len(_KNOB_INFO), align=4)
    _sh(7, '.dynamic', SHT_DYNAMIC, 0,
        0, dynamic_file_off, dynamic_size, link=9, entsize=8)
    _sh(8, '.dynsym',  SHT_DYNSYM, 0,
        0, dynsym_file_off, len(dynsym_data), link=9, entsize=16)
    _sh(9, '.dynstr',  SHT_STRTAB, 0,
        0, dynstr_file_off, len(dynstr_data))
    _sh(10, '.hash', SHT_HASH, 0,
        0, hash_file_off, len(hash_data), link=8)
    _sh(11, '.shstrtab', SHT_STRTAB, 0,
        0, shstrtab_file_off, len(shstr_data))

    # ----- Combine + optional audio NOP -----
    output = bytearray(zdl_hdr) + elf

    if cfg.audio_nop:
        audio_file_off = len(zdl_hdr) + text_file_off + AUDIO_OFF
        output[audio_file_off:audio_file_off + len(_NOP_RETURN)] = _NOP_RETURN

    Path(cfg.output_path).write_bytes(output)
    print(f"\n  → {cfg.output_path}  ({len(output)} bytes; ELF {elf_size})")


if __name__ == '__main__':
    print("This module is a library; call link(LinkerConfig(...)) from your build.py.")
    sys.exit(0)
