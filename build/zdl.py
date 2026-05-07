"""ZDL container reader/writer for Zoom MultiStomp .ZDL files.

A ZDL is a ZOOM-specific wrapper around a TI C674x ELF shared object:

    +---------+-----------------+---------------------+--------------+
    | NULL(4) | SIZE block (16) | INFO block (8 + 48) | ELF payload  |
    +---------+-----------------+---------------------+--------------+
       0..3       4..19              20..75              76..76+elf_size

All multi-byte integers are little-endian. The ZDL "magic" is four leading
zero bytes; ELF starts immediately after the INFO block at offset 76.

Reference: zoom-fx-modding-ref/library/CH_4.md
"""

from __future__ import annotations
import struct
from dataclasses import dataclass, field
from pathlib import Path

ZDL_NULL_PREFIX = b"\x00\x00\x00\x00"
ZDL_VERSION_STRING = b"ZOOM EFFECT DLL SYSTEM VER 1.00\x00"  # exactly 32 bytes
ELF_OFFSET = 76  # 4 (NULL) + 16 (SIZE) + 56 (INFO)
HEADER_SIZE_TYPICAL = 56  # size of remaining headers after SIZE block
INFO_PAYLOAD_SIZE = 48


# ---- FX type table (real_type field) --------------------------------
# From Zoom Firmware Editor's EffectType.java; see CH_4.md for context.
FX_TYPES = {
    1: "Dynamics", 2: "Filter", 3: "Drive", 4: "GuitarAmp",
    5: "BassAmp",  6: "Modulation", 7: "SFX", 8: "Delay",
    9: "Reverb",  11: "PedalOperated", 15: "ExtraDLL",
    20: "BassDrive", 22: "BassDrive",
}


@dataclass
class ZdlInfo:
    """The INFO block — describes how the unit categorizes/sorts the FX."""
    version_string: bytes = ZDL_VERSION_STRING  # 32 bytes, NUL-terminated
    real_type:     int = 2   # FX category (see FX_TYPES)
    unknown1:      int = 1   # observed values 0/1/20; meaning unknown
    knob_type:     int = 0   # 0=rotary, 1=slider, 2=LineSel-style frame
    unknown2:      int = 0
    sort_index:    int = 250 # menu sort key. Originals top out at 240; >240 is safe for new FX.
    sort_sub:      int = 0
    bass_flags:    int = 0   # correlated with bass-amp variants
    sort_fx_type:  int = 2   # category shown in UI sort
    fx_version:    bytes = b"1.01\x00\x00\x00\x00"  # exactly 8 bytes

    def pack(self) -> bytes:
        assert len(self.version_string) == 32
        assert len(self.fx_version) == 8
        return (
            self.version_string
            + bytes([
                self.real_type, self.unknown1, self.knob_type, self.unknown2,
                self.sort_index, self.sort_sub, self.bass_flags, self.sort_fx_type,
            ])
            + self.fx_version
        )

    @classmethod
    def unpack(cls, payload: bytes) -> "ZdlInfo":
        assert len(payload) == INFO_PAYLOAD_SIZE
        return cls(
            version_string=payload[0:32],
            real_type=payload[32], unknown1=payload[33],
            knob_type=payload[34], unknown2=payload[35],
            sort_index=payload[36], sort_sub=payload[37],
            bass_flags=payload[38], sort_fx_type=payload[39],
            fx_version=payload[40:48],
        )


@dataclass
class Zdl:
    """A parsed ZDL file: header metadata plus a raw ELF blob."""
    info: ZdlInfo
    elf:  bytes
    header_size: int = HEADER_SIZE_TYPICAL  # 56 typical; 232 with BCAB, 312 with CABI

    @classmethod
    def load(cls, path: str | Path) -> "Zdl":
        data = Path(path).read_bytes()
        if data[0:4] != ZDL_NULL_PREFIX:
            raise ValueError("not a ZDL: missing 4-byte NULL prefix")
        if data[4:8] != b"SIZE":
            raise ValueError("not a ZDL: missing SIZE block")
        size_payload, header_size, elf_size = struct.unpack("<III", data[8:20])
        if size_payload != 8:
            raise ValueError(f"unexpected SIZE payload {size_payload}")
        if data[20:24] != b"INFO":
            raise ValueError("not a ZDL: missing INFO block")
        info_size = struct.unpack("<I", data[24:28])[0]
        if info_size != INFO_PAYLOAD_SIZE:
            # BCAB (168) and CABI (248) extend the header; not handled here yet.
            raise NotImplementedError(f"INFO size {info_size} not supported")
        info = ZdlInfo.unpack(data[28:28 + INFO_PAYLOAD_SIZE])
        elf_start = 4 + 8 + 8 + header_size  # NULL + SIZEhdr + INFOhdr + payload
        elf = data[elf_start:elf_start + elf_size]
        if elf[:4] != b"\x7fELF":
            raise ValueError("ELF magic not found at expected offset")
        return cls(info=info, elf=elf, header_size=header_size)

    def pack(self) -> bytes:
        info_bytes = self.info.pack()
        assert len(info_bytes) == INFO_PAYLOAD_SIZE
        out = bytearray()
        out += ZDL_NULL_PREFIX
        out += b"SIZE" + struct.pack("<II", 8, self.header_size) + struct.pack("<I", len(self.elf))
        out += b"INFO" + struct.pack("<I", INFO_PAYLOAD_SIZE) + info_bytes
        out += self.elf
        return bytes(out)

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(self.pack())


# ---- ELF .const string patching ------------------------------------------
# Visible labels (effect name, knob captions) live in the .const section as
# null-padded ASCII slots. We don't link a fresh ELF; we just substitute
# in-place inside fixed-size slots. See howto/RTFM.md and CH_1.md.

def patch_label(elf: bytes, old: bytes, new: bytes, slot_size: int,
                anchor: bytes | None = None, anchor_offset: int = 0) -> bytes:
    """Replace a NUL-padded `old` label with `new` inside a fixed-size slot.

    Symbol/string tables in a TI ELF often contain the *same* ASCII as the
    on-screen label, so a plain string substitution is ambiguous. To target
    just the visible-label slot in `.const`, pass:
        anchor          — a unique byte pattern earlier in the ELF (e.g. b"OnOff\\x00")
        anchor_offset   — how many bytes after `anchor` the slot begins.
    With no anchor, the function falls back to requiring a unique match.
    """
    if len(new) >= slot_size:
        raise ValueError(f"new label {new!r} >= slot size {slot_size}")
    old_padded = old + b"\x00" * (slot_size - len(old))
    new_padded = new + b"\x00" * (slot_size - len(new))

    if anchor is not None:
        if elf.count(anchor) != 1:
            raise ValueError(f"anchor {anchor!r} not uniquely found in ELF")
        slot_start = elf.index(anchor) + len(anchor) + anchor_offset
        if elf[slot_start:slot_start + slot_size] != old_padded:
            raise ValueError(
                f"slot at {slot_start:#x} does not contain {old!r}; "
                f"found {elf[slot_start:slot_start + slot_size]!r}"
            )
        return elf[:slot_start] + new_padded + elf[slot_start + slot_size:]

    if elf.count(old_padded) != 1:
        raise ValueError(f"old label {old!r} not uniquely found in ELF — pass anchor=")
    return elf.replace(old_padded, new_padded, 1)
