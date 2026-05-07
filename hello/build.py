#!/usr/bin/env python3
"""Build HELLO.ZDL from manifest.json.

Strategy: load the MS-70CDR LineSel ZDL as a host, relabel its on-screen
name to "HELLO", and rewrite the INFO block so the unit treats it as a
distinct effect rather than overwriting LineSel. The DSP (a clean
input-passthrough by design of LineSel) is reused unmodified — this gives
us a known-good ELF on the unit before we start linking our own.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "build"))

from zdl import Zdl, ZdlInfo, patch_label  # noqa: E402


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    template = (HERE / manifest["template"]).resolve()
    output   = (HERE / manifest["output"]).resolve()

    print(f"[hello] template: {template}")
    z = Zdl.load(template)
    print(f"[hello] loaded ELF: {len(z.elf)} bytes")

    lbl = manifest["label"]
    anchor = bytes.fromhex(lbl["anchor_hex"]) if "anchor_hex" in lbl else None
    z.elf = patch_label(
        z.elf,
        lbl["old"].encode(), lbl["new"].encode(), lbl["slot_size"],
        anchor=anchor, anchor_offset=lbl.get("anchor_offset", 0),
    )
    print(f"[hello] relabeled: {lbl['old']!r} -> {lbl['new']!r}")

    info_in = manifest["info"]
    fx_ver  = info_in["fx_version"].encode()
    fx_ver  = fx_ver + b"\x00" * (8 - len(fx_ver))
    z.info = ZdlInfo(
        real_type    = info_in["real_type"],
        unknown1     = info_in["unknown1"],
        knob_type    = info_in["knob_type"],
        unknown2     = info_in["unknown2"],
        sort_index   = info_in["sort_index"],
        sort_sub     = info_in["sort_sub"],
        bass_flags   = info_in["bass_flags"],
        sort_fx_type = info_in["sort_fx_type"],
        fx_version   = fx_ver,
    )
    print(f"[hello] INFO sort_index={z.info.sort_index} real_type={z.info.real_type}")

    z.save(output)
    print(f"[hello] wrote: {output} ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
