#!/usr/bin/env python3
"""Build TapeHack.ZDL from tapehack.c + manifest.json."""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent      # src/airwindows/<name>/build.py → repo root
sys.path.insert(0, str(ROOT / "build"))

from linker import LinkerConfig, Param, link  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X    = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    # Skip --opt_for_space: at level 3 cl6x emits __local_call_stub thunks
    # in .text that dispatch through an empty $C$Tn table (TI's runtime
    # linker normally fills these with __c6xabi_divf etc.; ours doesn't).
    # The thunk branches to address 0 and freezes the pedal on load.
    # Plugin code is small enough that size opt isn't worth the indirection.
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())

    src_c   = HERE / "tapehack.c"
    obj     = HERE / "tapehack.obj"
    out_zdl = ROOT / "dist" / f"{manifest['effect_name']}.ZDL"
    out_zdl.parent.mkdir(exist_ok=True)

    print(f"[tapehack] compiling {src_c.name} → {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )

    cfg = LinkerConfig(
        effect_name      = manifest["effect_name"],
        audio_func_name  = manifest.get("audio_func_name"),
        gid              = manifest["gid"],
        fxid             = manifest["fxid"],
        params           = [Param(p["name"], p["max"], p["default"]) for p in manifest["params"]],
        obj_path         = obj,
        output_path      = out_zdl,
        fxid_version     = manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte       = manifest.get("flags_byte", 0x01),
        audio_nop        = manifest.get("audio_nop", False),
        # AIR's mix_edit (76 bytes, 0 .rela.dyn entries but apparently
        # internal hardcoded refs) crashes the pedal when invoked in
        # our context — when flags=0x14 / pmax=max enables actual
        # invocation of the entry [4] handler, the AIR blob freezes
        # the unit. Force NOP_RETURN until we have a synthesized,
        # truly self-contained knob3 edit handler. With NOP, knob 3
        # is a placeholder — it doesn't write params[7], so the audio
        # function reads stale memory there. (See docs/3-PARAM-LINKER-BUG.md.)
        knob3_blob_path  = "/tmp/__nonexistent__",
    )
    link(cfg)

    print(f"\n[tapehack] done → {out_zdl}")


if __name__ == "__main__":
    main()
