#!/usr/bin/env python3
"""Build CtxWatch.ZDL from ctxwatch.c + manifest.json (hardware probe).

manifest.json drives the desktop renderer; manifest.json drives this
build. They share the same 5 knobs, differing only in the quiet-safe Mix
default.

Requires the TI C6000 compiler at the TI_ROOT path below (edit if yours
differs). Run from the repo root:  python3 build_all.py ctxwatch
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent           # src/hardware_probes/ctxwatch/build.py -> repo root
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "src" / "airwindows" / "common"))

from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
from manifest_params import write_param_header  # noqa: E402
from custom_covers import make_cover  # noqa: E402

TI_ROOT = Path("/Applications/ti/ti-cgt-c6000_8.5.0.LTS")
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
    write_param_header(manifest, HERE / "ctxwatch_params.h", "CTXWATCH")

    src_c = HERE / "ctxwatch.c"
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)

    effect_name = manifest["effect_name"]
    audio_func = manifest["audio_func_name"]
    obj = HERE / f"{effect_name.lower()}.obj"
    out_zdl = out_dir / f"{effect_name}.ZDL"

    print(f"[ctxwatch] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            f"--define=CTXWATCH_AUDIO_FUNC={audio_func}",
            "-c",
            str(src_c),
            f"--output_file={obj}",
        ],
        check=True,
        cwd=HERE,
    )

    for junk in ("compiler.opt", "linker.cmd"):
        p = HERE / junk
        if p.exists():
            p.unlink()

    cfg = LinkerConfig(
        effect_name=effect_name,
        screen_image=make_cover(effect_name, [p["name"] for p in manifest["params"]]),
        audio_func_name=audio_func,
        gid=manifest["gid"],
        fxid=manifest["fxid"],
        params=params_from_manifest(manifest["params"]),
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        audio_nop=manifest.get("audio_nop", False),
        knob_positions=[(2, 14, 46), (3, 55, 46)],   # 2-knob probe
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
        knob3_blob_path="/tmp/__nonexistent__",
    )
    link(cfg)

    print(f"\n[ctxwatch] done -> {out_zdl}")


if __name__ == "__main__":
    main()
