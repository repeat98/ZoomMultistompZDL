#!/usr/bin/env python3
"""Build GAIN.ZDL from gain.c + manifest.json.

Steps:
  1. cl6x (TI C6000 v8.5)         gain.c → gain.obj
  2. linker.link(...)             gain.obj → GAIN.ZDL
"""

from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent      # src/airwindows/<name>/build.py → repo root
sys.path.insert(0, str(ROOT / "build"))

from linker import LinkerConfig, link, params_from_manifest  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X    = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    "--opt_for_space=3",
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",            # critical — see ABI.md §5.5
    f"--include_path={TI_ROOT}/include",
]


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())

    src_c   = HERE / "gain.c"
    obj     = HERE / "gain.obj"
    out_zdl = ROOT / "dist" / f"{manifest['effect_name']}.ZDL"
    out_zdl.parent.mkdir(exist_ok=True)

    print(f"[gain] compiling {src_c.name} → {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )

    # Strip CCS scratch dirs the compiler leaves behind.
    for junk in ("compiler.opt", "linker.cmd"):
        p = HERE / junk
        if p.exists():
            p.unlink()

    cfg = LinkerConfig(
        effect_name = manifest["effect_name"],
        gid         = manifest["gid"],
        fxid        = manifest["fxid"],
        params      = params_from_manifest(manifest["params"]),
        obj_path    = obj,
        output_path = out_zdl,
        fxid_version= manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte  = manifest.get("flags_byte", 0x01),
        audio_nop   = manifest.get("audio_nop", False),
    )
    link(cfg)

    print(f"\n[gain] done → {out_zdl}")


if __name__ == "__main__":
    main()
