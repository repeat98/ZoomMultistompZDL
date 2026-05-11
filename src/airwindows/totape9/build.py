#!/usr/bin/env python3
"""Build ToTape9.ZDL from totape9.c + manifest.json."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(HERE.parent / "common"))

from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
from airwindows_image import make_airwindows_tape_screen  # noqa: E402
from manifest_params import write_param_header  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    write_param_header(manifest, HERE / "totape9_params.h", "TOTAPE9")

    src_c = HERE / "totape9.c"
    obj = HERE / "totape9.obj"
    out_zdl = ROOT / "dist" / f"{manifest['effect_name']}.ZDL"
    out_zdl.parent.mkdir(exist_ok=True)

    print(f"[totape9] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )

    cfg = LinkerConfig(
        effect_name=manifest["effect_name"],
        audio_func_name=manifest.get("audio_func_name"),
        gid=manifest["gid"],
        fxid=manifest["fxid"],
        params=params_from_manifest(manifest["params"]),
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        screen_image=make_airwindows_tape_screen("ToTape", "9"),
        audio_nop=manifest.get("audio_nop", False),
        # Input/Tilt use LineSel's stock handlers. Shape and pages 2/3 use
        # LineSel-cloned handlers with patched knob ids/param offsets.
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
        knob3_blob_path="/tmp/__nonexistent__",
    )
    link(cfg)

    print(f"\n[totape9] done -> {out_zdl}")


if __name__ == "__main__":
    main()
