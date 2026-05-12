#!/usr/bin/env python3
"""Build StatePing fixed-word ZDL variants from stateping.c + manifest.json."""

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
    write_param_header(manifest, HERE / "stateping_params.h", "STATEPING")

    src_c = HERE / "stateping.c"
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    params = params_from_manifest(manifest["params"])
    variants = manifest.get("variants") or [manifest]
    outputs = []

    for variant in variants:
        fixed_word = int(variant.get("fixed_word", manifest.get("fixed_word", 0)))
        effect_name = variant.get("effect_name", manifest["effect_name"])
        fxid = int(variant.get("fxid", manifest["fxid"]))
        screen_label = variant.get("screen_label", effect_name)

        obj = HERE / f"stateping_w{fixed_word}.obj"
        out_zdl = out_dir / f"{effect_name}.ZDL"

        print(f"[stateping] compiling {src_c.name} -> {obj.name} (word {fixed_word})")
        subprocess.run(
            [
                str(CL6X),
                *CFLAGS,
                f"--define=STATEPING_FIXED_WORD={fixed_word}u",
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
            audio_func_name=manifest.get("audio_func_name"),
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

    print("\n[stateping] done")
    for out_zdl in outputs:
        print(f"  -> {out_zdl}")


if __name__ == "__main__":
    main()
