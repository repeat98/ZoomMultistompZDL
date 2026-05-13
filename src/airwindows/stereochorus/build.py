#!/usr/bin/env python3
"""Build fixed-stage StChorus probe ZDLs from stereochorus.c + manifest.json."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(HERE.parent / "common"))

from airwindows_image import make_airwindows_tape_screen  # noqa: E402
from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
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
    write_param_header(manifest, HERE / "stereochorus_params.h", "STCHORUS")

    src_c = HERE / "stereochorus.c"
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    params = params_from_manifest(manifest["params"])
    outputs = []

    for variant in manifest["variants"]:
        effect_name = variant["effect_name"]
        audio_func_name = variant["audio_func_name"]
        fixed_stage = int(variant["fixed_stage"])
        fxid = int(variant["fxid"])
        screen_label = variant.get("screen_label", effect_name)

        obj = HERE / f"{effect_name.lower()}.obj"
        out_zdl = out_dir / f"{effect_name}.ZDL"

        print(
            f"[stereochorus] compiling {src_c.name} -> {obj.name} "
            f"(fixed stage {fixed_stage})"
        )
        subprocess.run(
            [
                str(CL6X),
                *CFLAGS,
                f"--define=STCHORUS_AUDIO_FUNC={audio_func_name}",
                f"--define=STCHORUS_FIXED_STAGE={fixed_stage}",
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
            audio_func_name=audio_func_name,
            gid=manifest["gid"],
            fxid=fxid,
            params=params,
            obj_path=obj,
            output_path=out_zdl,
            fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
            flags_byte=manifest.get("flags_byte", 0x01),
            screen_image=make_airwindows_tape_screen(screen_label, ""),
            audio_nop=manifest.get("audio_nop", False),
        )
        link(cfg)
        outputs.append(out_zdl)

    stale = out_dir / "StChorus.ZDL"
    if stale.exists():
        stale.unlink()

    print("\n[stereochorus] done")
    for out_zdl in outputs:
        print(f"  -> {out_zdl}")


if __name__ == "__main__":
    main()
