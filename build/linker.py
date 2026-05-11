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
SHT_REL       = 9
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
    kind: str = "knob"   # knob | switch | enum | tempo (documented + future UI policy)
    min_val: int = 0     # documented lower bound; descriptor format stores max/default only
    pedal_max: Optional[int] = None
    reserved_a: int = 0
    reserved_b: int = 0
    flags: Optional[int] = None
    scale: str = "linear"
    unit: str = ""
    audio_min: float = 0.0
    audio_max: float = 1.0
    audio_default: Optional[float] = None
    labels: list[str] = field(default_factory=list)

    @classmethod
    def from_manifest(cls, raw: dict) -> "Param":
        kind = raw.get("type", raw.get("kind", "knob"))
        max_val = int(raw.get("max", raw.get("max_val", 1 if kind == "switch" else 100)))
        default_val = int(raw.get("default", raw.get("default_val", 0)))
        audio_default = raw.get("audio_default")
        return cls(
            name=raw["name"],
            max_val=max_val,
            default_val=default_val,
            kind=kind,
            min_val=int(raw.get("min", raw.get("min_val", 0))),
            pedal_max=raw.get("pedal_max"),
            reserved_a=int(raw.get("reserved_a", 0)),
            reserved_b=int(raw.get("reserved_b", 0)),
            flags=raw.get("flags"),
            scale=raw.get("scale", "linear"),
            unit=raw.get("unit", ""),
            audio_min=float(raw.get("audio_min", 0.0)),
            audio_max=float(raw.get("audio_max", 1.0)),
            audio_default=None if audio_default is None else float(audio_default),
            labels=list(raw.get("labels", [])),
        )

    @property
    def normalized_default(self) -> float:
        if self.audio_default is not None:
            return self.audio_default
        if self.max_val <= self.min_val:
            return 0.0
        return (self.default_val - self.min_val) / float(self.max_val - self.min_val)


def params_from_manifest(raw_params: list[dict]) -> list[Param]:
    return [Param.from_manifest(p) for p in raw_params]


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

    # Knob xy positions for the visible slots on the preview image. The
    # firmware paginates edit-mode parameters by walking the descriptor
    # table three-at-a-time. For >3 params, effectTypeImageInfo advertises
    # the total parameter count but still only provides the first 3 visible
    # coordinate slots, matching stock AIR-style paginated effects.
    #
    # Verified against 128 stock MS-70CDR ZDLs:
    #   2 params  → nknobs=2
    #   3+ params → nknobs=3
    #   0 params  → nknobs=0  (OrangeLM)
    # No stock effect uses nknobs=1; whether the firmware accepts it is
    # the next experiment.
    knob_positions: Optional[list[tuple[int, int, int]]] = None

    # Diagnostic override for hardware ABI experiments. Normal builds leave
    # this unset and use the stock-derived count rules in _build_image_info.
    image_info_knob_count: Optional[int] = None
    image_info_header_words: Optional[tuple[int, int]] = None

    # Diagnostic only: stock 3-knob effects have two .text relocations to a
    # coefficient table before the Dll descriptor/imageInfo relocations. Emit
    # equivalent relocs in dead .text padding to test old firmware parsers that
    # may expect this relocation prelude.
    emit_dummy_coe_relocs: bool = False

    # Stock MS-70CDR writable .fardata segments are tiny (largest observed:
    # 220 bytes). Large plugin static state has frozen hardware on load, so
    # keep custom builds inside the known-safe envelope unless a hardware
    # experiment explicitly opts out.
    max_fardata_bytes: int = 512
    allow_large_fardata: bool = False

    # Path to extracted __c6xabi_divf RTS code (640 bytes).
    divf_rts_path: Optional[str | os.PathLike] = None

    # Path to LineSel handler blob (480 bytes: onf + edit_a + edit_b + init
    # + __call_stub + RTS helpers, copied verbatim from LineSel's .text).
    # The blob provides real edit/onf handlers that read knob values from
    # the host runtime and write into params[5], params[6], params[0].
    # Without this, NOP_RETURN handlers are used and params[] stays
    # uninitialised. When set, handler_funcs maps logical names to byte
    # offsets within the blob: defaults match LineSel's layout.
    handler_blob_path: Optional[str | os.PathLike] = None
    handler_funcs: dict[str, int] = field(default_factory=lambda: {
        "onf":        0x000,   # OnOff toggle: writes params[0]
        "knob1_edit": 0x060,   # writes params[5] (knob_id=2)
        "knob2_edit": 0x0AC,   # writes params[6] (knob_id=3)
        "init":       0x0F8,   # has unresolved Coe-table refs; do NOT use
        "call_stub":  0x140,   # __c6xabi_call_stub — cl6x emits indirect
                               # calls through this when a function-pointer
                               # call needs register-bank switching, e.g.
                               # the Taylor-expansion thunks in TapeHack
        # 0x180  Dll_LineSel  — DEAD code, has stale relocs; never called
        "pop_rts":    0x1A0,   # __c6xabi_pop_rts (32 bytes)
        "push_rts":   0x1C0,   # __c6xabi_push_rts (32 bytes)
    })

    # Path to AIR knob3-edit blob (76 bytes, self-contained, 0 relocs).
    # Extracted from MS-70CDR_AIR.ZDL's `Fx_REV_Air_mix_edit` — the third
    # of three knobs in AIR. Hardcodes knob_id=4 and writes params[7].
    # Used when a plugin has a 3rd parameter. Knobs 4..9 fall back to
    # NOP_RETURN: no stock effect with >3 knobs has self-contained edit
    # handlers (LO-FI Dly's all reference effect-specific lookup tables),
    # so whether they update params[] is the open hardware question
    # tracked in ABI.md §5.3.b.
    knob3_blob_path: Optional[str | os.PathLike] = None

    # Audio-NOP override. When True, the audio function's first 32 bytes
    # are replaced with a canonical B B3 + delay-slot NOP sequence after
    # linking. Useful as a smoke test: lets the firmware exercise the UI
    # without running the plugin's DSP.
    audio_nop: bool = False

    # Diagnostic override. Normal builds prefer object-defined edit
    # handlers when present, because those are the only way knobs 3..9
    # can write real params. Set False to force blob/NOP handlers and
    # isolate whether a custom handler freezes during firmware init.
    use_object_edit_handlers: bool = True

    # Zero-based first parameter index allowed to use object-defined edit
    # handlers. This lets a plugin use the stock-proven LineSel/AIR
    # handlers for knobs 1-3 and custom generated handlers only for later
    # pages while we harden handler synthesis.
    object_edit_start_index: int = 0

    # Hardware-safe handler synthesis. Instead of compiling inline asm,
    # clone the complete LineSel handler blob for each requested knob so
    # the handler's relative calls to its local __c6xabi_call_stub remain
    # exactly stock-shaped. Only two compact MVK immediates are patched:
    # the host knob id and params[] byte offset.
    synthesize_linesel_edit_handlers: bool = False
    synth_edit_start_index: int = 2

    def __post_init__(self) -> None:
        if self.audio_func_name is None:
            self.audio_func_name = f"Fx_FLT_{self.effect_name}"
        if self.gid not in GID_PREFIX:
            raise ValueError(f"unknown gid {self.gid:#x}; add to GID_PREFIX table")

        # Hardware-confirmed ceiling for the MS-series UI path: 9 user
        # params, displayed as three pages of three edit-mode controls.
        # The preview image still only has coordinates for the first three
        # visible slots.
        if len(self.params) > 9:
            raise ValueError(
                f"{len(self.params)} params > 9 (3 pages × 3 visible knobs "
                f"is the apparent firmware ceiling — see ABI.md §3.1)"
            )
        image_count = self.image_info_knob_count
        n_visible = min(3, image_count if image_count is not None else len(self.params))
        defaults_by_count = {
            0: [],
            1: [(2, 54, 36)],
            2: [(2, 38, 36), (3, 70, 36)],
            3: [(2, 31, 36), (3, 55, 36), (4, 79, 36)],
        }
        if self.knob_positions is None:
            self.knob_positions = defaults_by_count[n_visible]
        elif len(self.knob_positions) != n_visible:
            raise ValueError(
                f"knob_positions has {len(self.knob_positions)} entries; "
                f"need {n_visible} (= min(3, n_params))"
            )
        if self.divf_rts_path is None:
            self.divf_rts_path = Path(__file__).resolve().parent / "divf_rts.bin"
        if self.handler_blob_path is None:
            self.handler_blob_path = Path(__file__).resolve().parent / "linesel_handlers.bin"
        if self.knob3_blob_path is None:
            self.knob3_blob_path = Path(__file__).resolve().parent / "air_knob3_edit.bin"


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
        # TI cl6x emits SHT_RELA when any reloc has a non-zero addend (e.g.
        # `previousSampleR @ +4`), and falls back to SHT_REL when all addends
        # are zero. We have to handle both — if we silently skip SHT_REL,
        # external calls (__c6xabi_divf, push_rts, pop_rts) link as
        # jumps-to-zero and crash the DSP at first audio callback.
        self.relocs: dict[int, list[dict]] = {}
        for s in self.sections:
            target_idx = s['info']
            entries = []
            if s['type'] == SHT_RELA:
                for i in range(s['size'] // 12):
                    off = i * 12
                    info = struct.unpack_from('<I', s['data'], off + 4)[0]
                    entries.append({
                        'offset': struct.unpack_from('<I', s['data'], off)[0],
                        'type':   info & 0xFF,
                        'sym_idx': info >> 8,
                        'addend': struct.unpack_from('<i', s['data'], off + 8)[0],
                    })
            elif s['type'] == SHT_REL:
                for i in range(s['size'] // 8):
                    off = i * 8
                    info = struct.unpack_from('<I', s['data'], off + 4)[0]
                    rtype = info & 0xFF
                    offset = struct.unpack_from('<I', s['data'], off)[0]
                    entries.append({
                        'offset': offset,
                        'type':   rtype,
                        'sym_idx': info >> 8,
                        # TI emits CALLP PCR relocations as SHT_REL with the
                        # instruction offset as the implicit addend. Without
                        # this, calls land early by their original section
                        # offset after we move .text/.audio in the final ZDL.
                        'addend': offset if rtype == RT_PCR_S21 else 0,
                    })
            if entries:
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
    # +0x28: non-zero IEEE-754 float — present in 821/821 stock MS-70CDR
    # effects (range 11.58..127.67, mean 37.23). Almost certainly a
    # CPU/memory cost estimate. Writing 0 here makes the firmware silently
    # drop params from the edit-mode UI even though the descriptor and
    # imageInfo declare them. See docs/3-PARAM-LINKER-BUG.md.
    # 20.0f (0x41a00000) is in the typical range for simple effects
    # (Exciter=19.51, OptComp=30.76, BitCrush=14.88, AutoPan=13.89).
    entry[0x28:0x2C] = struct.pack('<f', 20.0)
    relocs.append((len(desc) + 0x1C, init_func_va))
    relocs.append((len(desc) + 0x20, audio_func_va))
    desc.extend(entry)

    last_idx = len(params) - 1
    n_user = len(params)
    for i, p in enumerate(params):
        entry = bytearray(0x30)
        nb = p.name.encode('ascii')[:8]
        entry[:len(nb)] = nb
        _p32(entry, 0x0C, p.max_val)
        _p32(entry, 0x10, p.default_val)
        if p.pedal_max is not None:
            _p32(entry, 0x14, int(p.pedal_max))
        _p32(entry, 0x18, p.reserved_a)
        _p32(entry, 0x1C, knob_edit_vas[i])
        _p32(entry, 0x28, p.reserved_b)
        if i == last_idx:
            # Last-entry sentinel pattern is param-count-dependent
            # (verified across MS-70CDR stock 2026-05-10):
            #
            #   3 user params → flags=0x14, pedal_max=max_val
            #     (Exciter / OptComp / ZNR all match this exactly)
            #
            #   1, 2, 4..9 user params → flags=0x04, pedal_max=0
            #     (AIR with 6, LOFIDLY with 9, NoiseGate with 2 all
            #      use the simple 0x04 sentinel)
            #
            # Matches Exciter/OptComp/ZNR: 3-param plugins use flags=0x14
            # (sentinel | pedal) and pedal_max=max on the final parameter.
            # Earlier tests (2026-05-10) marked this as "no fix" in isolation,
            # but it is the correct on-disk ABI for 3-param effects.
            if p.flags is not None:
                _p32(entry, 0x2C, int(p.flags) | 0x04)
            elif n_user == 3:
                if p.pedal_max is None:
                    _p32(entry, 0x14, p.max_val)   # pedal_max = max
                _p32(entry, 0x2C, 0x14)            # flags = sentinel | stereo | pedal
            else:
                _p32(entry, 0x2C, 0x04)            # flags = sentinel only
        elif p.flags is not None:
            _p32(entry, 0x2C, int(p.flags) & ~0x04)
        relocs.append((len(desc) + 0x1C, knob_edit_vas[i]))
        desc.extend(entry)

    return bytes(desc), relocs


# ---------------------------------------------------------------------------
# effectTypeImageInfo — exactly 212 bytes. For paginated effects, the count
# field is the total user-param count, while only the first three coordinate
# blocks are populated; the rest of the fixed 212-byte struct is zero padding.
# ---------------------------------------------------------------------------

def _build_image_info(
    pic_va: int,
    knob_info_va: int,
    knob_positions: list[tuple[int, int, int]],
    total_knobs: int,
    knob_count_override: Optional[int] = None,
    header_words_override: Optional[tuple[int, int]] = None,
) -> tuple[bytes, list[tuple[int, int]]]:
    info = bytearray()
    relocs: list[tuple[int, int]] = []

    # Single-page plugins (<=3 knobs) like Exciter/OptComp advertise 3 in
    # the header. Multi-page plugins (AIR-style) advertise the total param
    # count in the count field, but still only carry three coordinate slots.
    effective_knobs = (
        knob_count_override
        if knob_count_override is not None
        else total_knobs if total_knobs > 3 else 3
    )

    # Header (32 bytes)
    info.extend(struct.pack('<I', 0))
    info.extend(struct.pack('<I', 1))
    info.extend(struct.pack('<I', 0))
    info.extend(struct.pack('<I', 128))
    info.extend(struct.pack('<I', 64))
    relocs.append((len(info), pic_va))
    info.extend(struct.pack('<I', pic_va))
    
    if header_words_override is not None:
        info.extend(struct.pack('<I', header_words_override[0]))
        info.extend(struct.pack('<I', header_words_override[1]))
    elif effective_knobs == 3:
        info.extend(struct.pack('<I', 32))  # Exciter/OptComp pattern
        info.extend(struct.pack('<I', 17))
    elif effective_knobs > 3:
        info.extend(struct.pack('<I', 21))  # AIR (paginated) pattern
        info.extend(struct.pack('<I', 23))
    else:
        info.extend(struct.pack('<I', 28))  # LineSel (1 or 2 knobs) pattern
        info.extend(struct.pack('<I', 17))

    # Knob count and coordinate slots
    info.extend(struct.pack('<I', effective_knobs))
    
    # Coordinate blocks. Only the first three visible slots are meaningful;
    # the 212-byte struct has enough zero padding for the advertised count.
    blocks = list(knob_positions)
    while len(blocks) < 3 and effective_knobs == 3:
        blocks.append((0, 0, 0))

    for kid, kx, ky in blocks:
        info.extend(struct.pack('<I', kid))
        info.extend(struct.pack('<I', kx))
        info.extend(struct.pack('<I', ky))
        if kid > 0:
            relocs.append((len(info), knob_info_va))
            info.extend(struct.pack('<I', knob_info_va))
        else:
            info.extend(struct.pack('<I', 0))

    if len(info) > 212:
        raise ValueError(f"effectTypeImageInfo is {len(info)} > 212 bytes")
    while len(info) < 212:
        info.append(0)
    return bytes(info), relocs


# KNOB_INFO {20, 15, 11, 0, 2, 0}: 24 bytes in .fardata. field4=2 ships in
# all 128 stock MS-70CDR ZDLs; v1 tried field4=5 once and the unit froze
# at FX-select time. Don't change.
_KNOB_INFO = struct.pack('<6I', 20, 15, 11, 0, 2, 0)


_COMPACT_MVK_S1_A4 = {
    20: 0x9212,
    24: 0x1A12,
    28: 0x9A12,
    32: 0x0232,
    36: 0x8232,
    40: 0x0A32,
    44: 0x8A32,
    48: 0x1232,
    52: 0x9232,
}

_COMPACT_MVK_L2_B4 = {
    2: 0x4627,
    3: 0x6627,
    4: 0x8627,
    5: 0xA627,
    6: 0xC627,
    7: 0xE627,
    8: 0x0E27,
    9: 0x2E27,
    10: 0x4E27,
}


def _patch_linesel_knob_clone(blob: bytes, knob_id: int, param_byte_off: int) -> bytes:
    """Clone LineSel's known-good knob1 handler block and retarget it.

    The returned blob is a full linesel_handlers.bin-sized block. Its
    handler lives at +0x60 and calls the cloned call_stub at +0x140, so no
    branch relocation/encoding changes are needed.
    """
    if param_byte_off not in _COMPACT_MVK_S1_A4:
        raise ValueError(f"no compact MVK.S1 A4 encoding for byte offset {param_byte_off}")
    if knob_id not in _COMPACT_MVK_L2_B4:
        raise ValueError(f"no compact MVK.L2 B4 encoding for knob id {knob_id}")
    out = bytearray(blob)
    # LineSel knob1 handler starts at +0x60. At +0x10 it has:
    #   MVK.L2 <knob_id>,B4
    _p16(out, 0x60 + 0x10, _COMPACT_MVK_L2_B4[knob_id])
    # At +0x44 it has:
    #   MVK.S1 <param_byte_off>,A4
    _p16(out, 0x60 + 0x44, _COMPACT_MVK_S1_A4[param_byte_off])
    return bytes(out)

# Stock 3-knob effects all export a local coefficient-table object before
# the UI/descriptor symbols. Simple test effects do not need coefficients,
# but keeping a zero-filled table preserves the stock local-symbol shape
# that the firmware's edit-mode path appears to care about.
_DUMMY_COE = bytes(0x44)


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
# 200-byte copy of NoiseGate's Dll function with 4 reloc points repatched
# to point at our descriptor table + effectTypeImageInfo. The first compact
# MVK writes the descriptor entry count into the host output struct:
#   OnOff + effect-name self-entry + user params.
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


def _encode_compact_mvk_l1_a0(value: int) -> int:
    """Return compact `MVK.L1 value,A0` encoding for small non-negative ints."""
    if value < 0 or value > 31:
        raise ValueError(f"DLL descriptor count {value} out of compact MVK range")
    # Observed stock encodings:
    #   4 -> 0x8426 (NoiseGate, 2 user params)
    #   5 -> 0xA426 (Exciter/OptComp, 3 user params)
    #   9 -> 0x2C26 (GraphicEQ, 7 user params)
    hi = ((value & 0x7) << 5) | ((value >> 3) << 3) | 0x04
    return (hi << 8) | 0x26


def _build_dll(desc_entry_count: int) -> bytes:
    code = bytearray()
    words = list(_DLL_WORDS)
    words[0] = (words[0] & 0x0000FFFF) | (_encode_compact_mvk_l1_a0(desc_entry_count) << 16)
    for w in words:
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

    object_symbol_names = {sym['name'] for sym in obj.symbols if sym['name']}

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

    # ----- Build LineSel-cloned synthetic edit handlers -----
    synth_handler_blob = b""
    synth_handler_vas_by_param: dict[int, int] = {}
    synth_specs: list[tuple[int, int, int]] = []
    if cfg.synthesize_linesel_edit_handlers:
        if not use_real_handlers:
            raise RuntimeError("LineSel handler synthesis requires handler_blob_path")
        for i in range(len(cfg.params)):
            if i >= cfg.synth_edit_start_index:
                synth_specs.append((i, i + 2, 20 + i * 4))
        if synth_specs:
            synth_parts = [
                _patch_linesel_knob_clone(handler_blob, knob_id, param_off)
                for _, knob_id, param_off in synth_specs
            ]
            synth_handler_blob = b"".join(synth_parts)
            print(
                f"  synth:   {len(synth_specs)} LineSel-cloned edit handler(s) "
                f"({len(synth_handler_blob)} bytes)"
            )

    # ----- Load AIR knob3 blob (used when len(params) >= 3) -----
    knob3_blob = b""
    knob3_path = Path(cfg.knob3_blob_path) if cfg.knob3_blob_path else None
    use_knob3 = (knob3_path is not None and knob3_path.exists()
                 and len(cfg.params) >= 3)
    if use_knob3:
        knob3_blob = knob3_path.read_bytes()
        print(f"  knob3:    {knob3_path.name} ({len(knob3_blob)} bytes)")

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
    SYNTH_OFF       = _align_up(HANDLER_OFF + HANDLER_SIZE, 32)
    SYNTH_SIZE      = len(synth_handler_blob)
    KNOB3_OFF       = _align_up(SYNTH_OFF + SYNTH_SIZE, 32)
    KNOB3_SIZE      = len(knob3_blob)
    DIVF_OFF        = _align_up(KNOB3_OFF + KNOB3_SIZE, 32)
    DIVF_SIZE       = len(divf_code)

    # NOP_RETURN stubs — we need one PER NOP'd-handler-role so each
    # named dynsym entry (Fx_FLT_<Name>_init, Fx_FLT_<Name>_KnobN_edit
    # etc.) gets a unique VA. Shared VAs cause va_to_idx collisions
    # where one named handler overwrites another's reloc resolution —
    # the firmware then sees `Fx_FLT_<Name>_init` actually pointing at
    # the symbol named for a different role and silently drops the
    # affected entry from the edit-mode list (verified hardware test
    # 2026-05-11 with HELLO).
    #
    # Pre-count NOP roles: init (always NOP), plus one per knob that
    # falls back to NOP_RETURN.
    use_real_knob1    = use_real_handlers and "knob1_edit" in cfg.handler_funcs and len(cfg.params) >= 1
    use_real_knob2    = use_real_handlers and "knob2_edit" in cfg.handler_funcs and len(cfg.params) >= 2
    use_real_knob3    = use_knob3       and len(cfg.params) >= 3
    nop_knob_count    = sum(1 for i in range(len(cfg.params))
                            if not (
                                (
                                    cfg.synthesize_linesel_edit_handlers
                                    and i >= cfg.synth_edit_start_index
                                ) or
                                (
                                    cfg.use_object_edit_handlers
                                    and i >= cfg.object_edit_start_index
                                    and f"{cfg.audio_func_name}_{cfg.params[i].name.replace(' ', '')}_edit"
                                    in object_symbol_names
                                ) or
                                (i == 0 and use_real_knob1) or
                                (i == 1 and use_real_knob2) or
                                (i == 2 and use_real_knob3)
                            ))

    nop_onf_needed    = 1 if (not use_real_handlers or "onf" not in cfg.handler_funcs) else 0
    NOP_RETURN_COUNT  = 1 + nop_knob_count + nop_onf_needed   # init + NOP'd knobs + (maybe) onf
    NOP_RET_OFF       = _align_up(DIVF_OFF + DIVF_SIZE, 32)
    NOP_RET_STUB_SIZE = 32
    NOP_RET_SIZE      = NOP_RET_STUB_SIZE * NOP_RETURN_COUNT
    DLL_OFF           = NOP_RET_OFF + NOP_RET_SIZE
    DLL_SIZE          = 200
    TEXT_TOTAL        = _align_up(DLL_OFF + DLL_SIZE, 32)

    print(f"\n  .text layout:")
    print(f"    audio    @ 0x{AUDIO_OFF:04X}  ({audio_sec['size']} → padded {AUDIO_PAD})")
    print(f"    text     @ 0x{TEXT_ORIG_OFF:04X}  ({TEXT_ORIG_SIZE})")
    if HANDLER_SIZE:
        print(f"    handlers @ 0x{HANDLER_OFF:04X}  ({HANDLER_SIZE})")
    if SYNTH_SIZE:
        print(f"    synth    @ 0x{SYNTH_OFF:04X}  ({SYNTH_SIZE})")
    if KNOB3_SIZE:
        print(f"    knob3    @ 0x{KNOB3_OFF:04X}  ({KNOB3_SIZE})")
    print(f"    divf     @ 0x{DIVF_OFF:04X}  ({DIVF_SIZE})")
    print(f"    nop_ret  @ 0x{NOP_RET_OFF:04X}  ({NOP_RETURN_COUNT} × 32-byte stubs)")
    print(f"    Dll      @ 0x{DLL_OFF:04X}")
    print(f"    total      0x{TEXT_TOTAL:X}")

    # ----- Build .text -----
    out_text = bytearray(TEXT_TOTAL)
    out_text[AUDIO_OFF:AUDIO_OFF + audio_sec['size']] = audio_sec['data']
    if text_sec and TEXT_ORIG_SIZE:
        out_text[TEXT_ORIG_OFF:TEXT_ORIG_OFF + TEXT_ORIG_SIZE] = text_sec['data']
    if HANDLER_SIZE:
        out_text[HANDLER_OFF:HANDLER_OFF + HANDLER_SIZE] = handler_blob
    if SYNTH_SIZE:
        out_text[SYNTH_OFF:SYNTH_OFF + SYNTH_SIZE] = synth_handler_blob
    if KNOB3_SIZE:
        out_text[KNOB3_OFF:KNOB3_OFF + KNOB3_SIZE] = knob3_blob
    out_text[DIVF_OFF:DIVF_OFF + DIVF_SIZE] = divf_code
    # Emit NOP_RETURN_COUNT distinct 32-byte stubs (each is the same byte
    # sequence — `B B3` + delay-slot NOPs — but they live at distinct
    # VAs so different roles using NOP_RETURN don't collide in va_to_idx).
    for k in range(NOP_RETURN_COUNT):
        stub_off = NOP_RET_OFF + k * NOP_RET_STUB_SIZE
        out_text[stub_off:stub_off + NOP_RET_STUB_SIZE] = _NOP_RETURN
    out_text[DLL_OFF:DLL_OFF + DLL_SIZE] = _build_dll(2 + len(cfg.params))

    # Resolve handler VAs (one per logical name)
    if use_real_handlers:
        for name, off in cfg.handler_funcs.items():
            handler_va[name] = TEXT_VA + HANDLER_OFF + off
    if synth_specs:
        for clone_idx, (param_idx, _knob_id, _param_off) in enumerate(synth_specs):
            synth_handler_vas_by_param[param_idx] = (
                TEXT_VA + SYNTH_OFF + clone_idx * len(handler_blob) + 0x60
            )
    if use_knob3:
        handler_va["knob3_edit"] = TEXT_VA + KNOB3_OFF

    # ----- Map .obj sections to VAs -----
    section_va: dict[int, int] = {
        audio_sec['idx']: TEXT_VA + AUDIO_OFF,
    }
    if text_sec:
        section_va[text_sec['idx']] = TEXT_VA + TEXT_ORIG_OFF

    obj_symbol_va: dict[str, int] = {}
    for sym in obj.symbols:
        if sym['name'] and sym['shndx'] in section_va:
            obj_symbol_va[sym['name']] = section_va[sym['shndx']] + sym['value']

    # =====================================================================
    # Build .const layout
    # =====================================================================
    const_data = bytearray(pic_data)

    DESC_OFF_IN_CONST = _align_up(len(const_data), 4)
    _pad_to(const_data, DESC_OFF_IN_CONST)

    # Sequential allocator over the NOP_RETURN stub region. Each role
    # that needs a NOP_RETURN handler gets a UNIQUE stub VA so the
    # named dynsym entries (Fx_FLT_<Name>_init, Fx_FLT_<Name>_KnobN_edit)
    # never collide in va_to_idx (which uses latest-VA-wins). Without
    # unique VAs, a NOP'd knob entry's func_ptr reloc resolves to a
    # symbol with someone else's name, and the firmware silently drops
    # the affected param from the edit-mode list (verified hardware
    # test 2026-05-11 with HELLO).
    next_nop_stub = [0]
    def _alloc_nop_va() -> int:
        if next_nop_stub[0] >= NOP_RETURN_COUNT:
            raise RuntimeError(
                f"out of NOP_RETURN stubs (NOP_RETURN_COUNT={NOP_RETURN_COUNT}); "
                f"increase pre-count above"
            )
        va = TEXT_VA + NOP_RET_OFF + next_nop_stub[0] * NOP_RET_STUB_SIZE
        next_nop_stub[0] += 1
        return va

    onf_va  = handler_va["onf"] if "onf" in handler_va else _alloc_nop_va()
    init_va = _alloc_nop_va()    # init always NOPs (no real init synthesized yet)

    # Per-knob edit handlers.
    #   knob 1 → LineSel knob1_edit (if blob present)
    #   knob 2 → LineSel knob2_edit (if blob present)
    #   knob 3 → AIR knob3 blob (legacy fallback only; it is not
    #            portable to every plugin context)
    #   synthesized LineSel clones / object-defined handlers can override
    #   this before falling back to blob/NOP handlers.
    edit_keys = ["knob1_edit", "knob2_edit", "knob3_edit"]
    knob_edit_vas: list[int] = []
    n_nop_handlers = 0
    for i, param in enumerate(cfg.params):
        p_name = param.name.replace(' ', '')
        obj_edit_name = f"{cfg.audio_func_name}_{p_name}_edit"
        key = edit_keys[i] if i < len(edit_keys) else None
        real_va = synth_handler_vas_by_param.get(i)
        if real_va is None:
            real_va = (
                obj_symbol_va.get(obj_edit_name)
                if cfg.use_object_edit_handlers and i >= cfg.object_edit_start_index
                else None
            )
        if real_va is None:
            real_va = handler_va.get(key) if key else None

        if real_va is not None:
            knob_edit_vas.append(real_va)
        else:
            knob_edit_vas.append(_alloc_nop_va())
            n_nop_handlers += 1
    if n_nop_handlers:
        print(f"  WARNING: {n_nop_handlers} knob(s) using NOP_RETURN edit "
              f"handler (each gets a unique stub VA)")

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

    # Compute the final fardata address before writing imageInfo, because
    # imageInfo contains absolute relocations to _infoEffectTypeKnob_A_2.
    obj_const_sec = obj.get_section('.const')
    after_info = INFO_OFF_IN_CONST + 212
    coe_off_est = _align_up(after_info, 4)
    after_coe = coe_off_est + len(_DUMMY_COE)
    if obj_const_sec and obj_const_sec['size'] > 0:
        after_coe = _align_up(after_coe, max(obj_const_sec['align'], 4)) + obj_const_sec['size']
    CONST_SIZE = _align_up(after_coe, 8)
    FARDATA_VA   = CONST_VA + CONST_SIZE
    KNOB_INFO_VA = FARDATA_VA
    OUR_FARDATA_VA = FARDATA_VA + len(_KNOB_INFO)

    info_bytes, info_relocs = _build_image_info(
        pic_va=PIC_VA,
        knob_info_va=KNOB_INFO_VA,
        knob_positions=cfg.knob_positions,
        total_knobs=len(cfg.params),
        knob_count_override=cfg.image_info_knob_count,
        header_words_override=cfg.image_info_header_words,
    )
    const_data.extend(info_bytes)

    COE_OFF_IN_CONST = _align_up(len(const_data), 4)
    _pad_to(const_data, COE_OFF_IN_CONST)
    COE_VA = CONST_VA + COE_OFF_IN_CONST
    const_data.extend(_DUMMY_COE)

    # Append the .obj's own .const data (compiler-emitted constants — float
    # divisor tables, jump tables, etc.). Without this, any cross-section
    # MVKL/MVKH reference into .const links unresolved and the audio code
    # reads zero. TapeHack's Taylor coefficients hit this path.
    obj_const_off_in_const = None
    if obj_const_sec and obj_const_sec['size'] > 0:
        obj_const_off_in_const = _align_up(len(const_data), max(obj_const_sec['align'], 4))
        _pad_to(const_data, obj_const_off_in_const)
        const_data.extend(obj_const_sec['data'])

    CONST_SIZE = _align_up(len(const_data), 8)
    _pad_to(const_data, CONST_SIZE)
    FARDATA_VA   = CONST_VA + CONST_SIZE
    KNOB_INFO_VA = FARDATA_VA
    OUR_FARDATA_VA = FARDATA_VA + len(_KNOB_INFO)

    if obj_const_sec and obj_const_off_in_const is not None:
        section_va[obj_const_sec['idx']] = CONST_VA + obj_const_off_in_const

    print(f"\n  .const layout:")
    print(f"    picture    @ 0x{0:04X}  ({pic_end})")
    print(f"    descriptor @ 0x{DESC_OFF_IN_CONST:04X}  ({len(desc_bytes)})")
    print(f"    imageInfo  @ 0x{INFO_OFF_IN_CONST:04X}  ({len(info_bytes)})")
    if obj_const_sec and obj_const_off_in_const is not None:
        print(f"    obj.const  @ 0x{obj_const_off_in_const:04X}  ({obj_const_sec['size']})")
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
    if len(fardata_data) > cfg.max_fardata_bytes and not cfg.allow_large_fardata:
        raise RuntimeError(
            f".fardata image is {len(fardata_data)} bytes, above the "
            f"{cfg.max_fardata_bytes}-byte hardware-safe limit. Large writable "
            "segments have frozen MS-series pedals on load; remove static state "
            "or set allow_large_fardata=True for an explicit hardware probe."
        )

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

    # Compiler-emitted register save/restore helpers — resolve to the
    # spliced LineSel copies if present.  Without these, any moderately
    # complex audio function (anything that spills to stack) would link
    # as unresolved and crash at first call.
    for ext_name, blob_key in [
        ('__c6xabi_push_rts', 'push_rts'),
        ('__c6xabi_pop_rts',  'pop_rts'),
        ('__c6xabi_call_stub','call_stub'),
    ]:
        if ext_name in undefined and blob_key in handler_va:
            sym_addr[undefined[ext_name]] = handler_va[blob_key]

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
    coe_relocs: list[tuple[int, int, int]] = []
    if cfg.emit_dummy_coe_relocs:
        coe_reloc_off = DLL_OFF + DLL_SIZE
        if coe_reloc_off + 0x10 > TEXT_TOTAL:
            raise RuntimeError("not enough .text padding for dummy Coe relocs")
        # Dead padding after Dll_<Name>. These words are never executed, but
        # using MVK/MVKH-shaped instructions keeps the relocation records
        # structurally close to stock Exciter.
        struct.pack_into('<I', out_text, coe_reloc_off + 0x00, 0x0001AC2A)
        struct.pack_into('<I', out_text, coe_reloc_off + 0x0C, 0x0040006B)
        _patch_abs_l16(out_text, coe_reloc_off + 0x00, COE_VA)
        _patch_abs_h16(out_text, coe_reloc_off + 0x0C, COE_VA)
        coe_relocs.append((TEXT_VA + coe_reloc_off + 0x00, RT_ABS_L16, COE_VA))
        coe_relocs.append((TEXT_VA + coe_reloc_off + 0x0C, RT_ABS_H16, COE_VA))

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
    all_rela: list[tuple[int, int, int]] = list(coe_relocs) + list(dyn_relocs)
    for off_in_desc, func_va in desc_relocs:
        all_rela.append((DESC_VA + off_in_desc, RT_ABS32, func_va))
    for off_in_info, ptr_va in info_relocs:
        all_rela.append((INFO_VA + off_in_info, RT_ABS32, ptr_va))

    # Each unique target VA gets one dynsym entry.
    dynsym_targets: dict[int, int] = {tgt: 0 for _, _, tgt in all_rela}

    # =====================================================================
    # Build .dynsym / .dynstr
    # =====================================================================
    # ELF spec requires all STB_LOCAL syms to precede all STB_GLOBAL syms.
    # The host firmware loader also appears to expect a specific order and
    # visibility (verified against Exciter 2026-05-10).
    dynstr = _StringTable()
    dynsym_list = []
    # Index 0: NULL symbol
    dynsym_list.append({'name': '', 'name_idx': 0, 'value': 0, 'size': 0, 'info': 0, 'st_other': 0, 'shndx': 0})
    
    va_to_idx = {}
    STV_HIDDEN = 2
    STV_PROTECTED = 3

    def _shndx(va: int) -> int:
        if va < 0x80000000: return 4 # .text
        return 6 if va >= FARDATA_VA else 5 # .fardata or .const

    def _add_sym(name, value, size, stype, bind, visibility, shndx=None, map_reloc=True):
        idx = len(dynsym_list)
        dynsym_list.append({
            'name': name,
            'name_idx': dynstr.add(name),
            'value': value,
            'size': size,
            'info': (bind << 4) | stype,
            'st_other': visibility,
            'shndx': shndx if shndx is not None else _shndx(value),
        })
        if map_reloc:
            va_to_idx[value] = idx
        return idx

    # 1. Start with relocation targets (unnamed locals)
    abi_vas = {TEXT_VA + AUDIO_OFF, DESC_TABLE_VA, INFO_VA, PIC_VA, KNOB_INFO_VA, TEXT_VA + NOP_RET_OFF, onf_va, init_va}
    abi_vas.update(knob_edit_vas)

    for tgt in sorted(dynsym_targets.keys()):
        if tgt not in abi_vas:
            stype = STT_FUNC if tgt < 0x80000000 else STT_OBJECT
            _add_sym('', tgt, 0, stype, STB_LOCAL, STV_HIDDEN)

    # 2. Add ABI-required local symbols in the same broad order as stock
    # 3-knob effects: data, edit handlers in reverse descriptor order,
    # audio/init/onf, then imageInfo + descriptor. The firmware should use
    # relocations, but hardware tests show the edit-mode path is sensitive
    # to details the loader's normal relocation path ignores.
    _add_sym(f'_{cfg.audio_func_name}_Coe', COE_VA, len(_DUMMY_COE), STT_OBJECT, STB_LOCAL, STV_HIDDEN)
    _add_sym('_infoEffectTypeKnob_A_2', KNOB_INFO_VA, len(_KNOB_INFO), STT_OBJECT, STB_LOCAL, STV_HIDDEN)
    _add_sym(f'picEffectType_{cfg.effect_name}', PIC_VA, pic_end, STT_OBJECT, STB_LOCAL, STV_HIDDEN)
    for i in reversed(range(len(knob_edit_vas))):
        p_name = cfg.params[i].name.replace(' ', '')
        _add_sym(f"{cfg.audio_func_name}_{p_name}_edit", knob_edit_vas[i], 0, STT_FUNC, STB_LOCAL, STV_HIDDEN)
    _add_sym(cfg.audio_func_name, TEXT_VA + AUDIO_OFF, 0, STT_FUNC, STB_LOCAL, STV_HIDDEN)
    _add_sym(f"{cfg.audio_func_name}_init", init_va, 0, STT_FUNC, STB_LOCAL, STV_HIDDEN)
    _add_sym(f"{cfg.audio_func_name}_onf", onf_va, 0, STT_FUNC, STB_LOCAL, STV_HIDDEN)
    _add_sym('effectTypeImageInfo', INFO_VA, len(info_bytes), STT_OBJECT, STB_LOCAL, STV_HIDDEN)
    _add_sym('SonicStomp', DESC_TABLE_VA, len(desc_bytes), STT_OBJECT, STB_LOCAL, STV_HIDDEN)

    # 3. Profiling/static-base locals (SHN_ABS)
    SHN_ABS = 0xFFF1
    for sn in ('__TI_STATIC_BASE', '__TI_pprof_out_hndl', '__TI_prof_data_size', '__TI_prof_data_start'):
        val = 0xFFFFFFFF if 'pprof' in sn or 'prof_data' in sn else 0
        shndx = SHN_ABS if val == 0xFFFFFFFF else 0
        # These ABI bookkeeping symbols are not relocation targets for our
        # descriptor. In particular, __TI_STATIC_BASE has value 0, same as
        # the audio function, and must not steal the name entry's audio_ptr
        # relocation from Fx_FLT_<Name>.
        _add_sym(sn, val, 0, STT_NOTYPE, STB_LOCAL, STV_HIDDEN, shndx=shndx, map_reloc=False)

    # 4. DLL Entry (STB_GLOBAL)
    first_global_idx = len(dynsym_list)
    dll_name = f'Dll_{cfg.effect_name}'
    dll_name_idx = dynstr.add(dll_name)
    dll_sym_idx = _add_sym(dll_name, TEXT_VA + DLL_OFF, 0, STT_FUNC, STB_GLOBAL, STV_PROTECTED)

    # SONAME — must follow `ZDL_<GID_PREFIX>_<Name>.out` or the firmware
    # falls back to a 2-knob no-page mode.
    soname = f'ZDL_{GID_PREFIX[cfg.gid]}_{cfg.effect_name}.out'
    soname_idx = dynstr.add(soname)

    # ----- Pack dynamic structures -----
    rela_dyn_data = bytearray()
    for va, rtype, tgt in all_rela:
        sym_idx = va_to_idx.get(tgt, 0)
        rela_dyn_data.extend(struct.pack('<Iii', va, (sym_idx << 8) | rtype, 0))

    dynsym_data = bytearray()
    for s in dynsym_list:
        dynsym_data.extend(struct.pack('<III', s['name_idx'], s['value'], s['size']))
        dynsym_data.append(s['info'])
        dynsym_data.append(s.get('st_other', 0))                 # visibility
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

    # .c6xabi.attributes — required per SPRAB89B Ch.17. Stock effects
    # all carry one. Without it, the loader can't tell what addressing
    # model we use and falls back to a degraded path. We splice stock
    # Exciter's 62-byte blob verbatim (Tag_ISA=C6740, ABI_DSBT/PID/PIC
    # all matching the bare-metal-non-DSBT model we actually produce).
    c6xabi_path = Path(__file__).resolve().parent / "c6xabi_attributes.bin"
    c6xabi_attrs = c6xabi_path.read_bytes()

    # Stock ZDL ELFs place .text at file offset 0x40 and put the program
    # header table near EOF, immediately before the section headers. Keep
    # that shape: the normal loader follows e_phoff either way, but the
    # firmware's edit-mode path appears to have an older parser with layout
    # assumptions.
    cur = ELF_HDR_SIZE
    text_file_off = _align_up(cur, 32);                cur = text_file_off + TEXT_TOTAL
    const_file_off = _align_up(cur, 8);                cur = const_file_off + CONST_SIZE
    # .fardata includes the common 24-byte knob bitmap followed by any
    # plugin .fardata/.far state. Keep filesz == memsz: stock effects store
    # zero-initialized state as literal zero bytes in the file image rather
    # than asking the loader for a BSS extension.
    fardata_file_off = _align_up(cur, 4);              cur = fardata_file_off + len(fardata_data)
    rela_dyn_file_off = _align_up(cur, 4);             cur = rela_dyn_file_off + len(rela_dyn_data)
    rela_plt_file_off = cur                            # empty
    dynamic_size = 21 * 8                              # match Exciter
    dynamic_file_off = _align_up(cur, 4);              cur = dynamic_file_off + dynamic_size
    dynsym_file_off = _align_up(cur, 4);               cur = dynsym_file_off + len(dynsym_data)
    dynstr_file_off = _align_up(cur, 4);               cur = dynstr_file_off + len(dynstr_data)
    hash_file_off = _align_up(cur, 4);                 cur = hash_file_off + len(hash_data)
    c6xabi_file_off = _align_up(cur, 4);               cur = c6xabi_file_off + len(c6xabi_attrs)

    shstr = _StringTable()
    shstr_names = ['', '.rela.dyn', '.rela.plt', '.audio', '.text',
                   '.const', '.fardata', '.dynamic', '.dynsym', '.dynstr',
                   '.hash', '.c6xabi.attributes', '.shstrtab']
    shname_idx = {n: shstr.add(n) for n in shstr_names}
    shstr_data = shstr.get_bytes()
    shstrtab_file_off = _align_up(cur, 4);             cur = shstrtab_file_off + len(shstr_data)

    NUM_SECTIONS = 13
    SHDR_SIZE    = 0x28
    phdr_file_off = cur;                               cur = phdr_file_off + PHDR_TABLE
    shdr_file_off = cur;                               cur = shdr_file_off + NUM_SECTIONS * SHDR_SIZE
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
    _p32(elf, 0x1C, phdr_file_off)                              # e_phoff
    _p32(elf, 0x20, shdr_file_off)                              # e_shoff
    _p32(elf, 0x24, 0)
    _p16(elf, 0x28, ELF_HDR_SIZE)
    _p16(elf, 0x2A, PHDR_SIZE)
    _p16(elf, 0x2C, NUM_PHDRS)
    _p16(elf, 0x2E, SHDR_SIZE)
    _p16(elf, 0x30, NUM_SECTIONS)
    _p16(elf, 0x32, NUM_SECTIONS - 1)                           # e_shstrndx

    p = phdr_file_off
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
    # PT_LOAD .fardata rw-, memsz == filesz, no BSS extension.
    _p32(elf, p+0x00, PT_LOAD); _p32(elf, p+0x04, fardata_file_off)
    _p32(elf, p+0x08, FARDATA_VA); _p32(elf, p+0x0C, FARDATA_VA)
    _p32(elf, p+0x10, len(fardata_data)); _p32(elf, p+0x14, len(fardata_data))
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
    elf[fardata_file_off:fardata_file_off + len(fardata_data)] = fardata_data
    elf[rela_dyn_file_off:rela_dyn_file_off + len(rela_dyn_data)] = rela_dyn_data
    elf[dynamic_file_off:dynamic_file_off + len(dyn)]          = dyn
    elf[dynsym_file_off:dynsym_file_off + len(dynsym_data)]    = dynsym_data
    elf[dynstr_file_off:dynstr_file_off + len(dynstr_data)]    = dynstr_data
    elf[hash_file_off:hash_file_off + len(hash_data)]          = hash_data
    elf[c6xabi_file_off:c6xabi_file_off + len(c6xabi_attrs)]   = c6xabi_attrs
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
        FARDATA_VA, fardata_file_off, len(fardata_data), align=4)
    _sh(7, '.dynamic', SHT_DYNAMIC, 0,
        0, dynamic_file_off, dynamic_size, link=9, entsize=8)
    # SHT_DYNSYM info field: ELF spec mandates this be the index of the
    # first STB_GLOBAL symbol. Stock effects all set this correctly; v1's
    # linker left it 0 — fine for ≤2 params but breaks 3-param render.
    _sh(8, '.dynsym',  SHT_DYNSYM, 0,
        0, dynsym_file_off, len(dynsym_data),
        link=9, info=first_global_idx, entsize=16)
    _sh(9, '.dynstr',  SHT_STRTAB, 0,
        0, dynstr_file_off, len(dynstr_data))
    _sh(10, '.hash', SHT_HASH, 0,
        0, hash_file_off, len(hash_data), link=8)
    # SHT_C6000_ATTRIBUTES = 0x70000003 (SHT_LOPROC + 3) per SPRAB89B Ch.17.
    # Stock effects emit this as a non-allocated, non-loaded section.
    _sh(11, '.c6xabi.attributes', 0x70000003, 0,
        0, c6xabi_file_off, len(c6xabi_attrs))
    _sh(12, '.shstrtab', SHT_STRTAB, 0,
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
