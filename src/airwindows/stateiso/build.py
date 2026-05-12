#!/usr/bin/env python3
"""Build StateIso fixed-magic ZDL variants from stateiso.c + manifest.json."""

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


def parse_u32(raw: str | int) -> int:
    if isinstance(raw, int):
        return raw & 0xFFFFFFFF
    return int(raw, 0) & 0xFFFFFFFF


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    write_param_header(manifest, HERE / "stateiso_params.h", "STATEISO")

    src_c = HERE / "stateiso.c"
    out_dir = ROOT / "dist"
    out_dir.mkdir(exist_ok=True)
    params = params_from_manifest(manifest["params"])
    variants = manifest.get("variants") or [manifest]
    outputs = []

    for variant in variants:
        effect_name = variant.get("effect_name", manifest["effect_name"])
        audio_func_name = variant.get("audio_func_name", manifest.get("audio_func_name"))
        if audio_func_name is None:
            audio_func_name = f"Fx_FLT_{effect_name}"
        fxid = int(variant.get("fxid", manifest["fxid"]))
        magic = parse_u32(variant.get("magic", "0x13579BDF"))
        screen_label = variant.get("screen_label", effect_name)

        obj = HERE / f"{effect_name.lower()}.obj"
        out_zdl = out_dir / f"{effect_name}.ZDL"

        print(f"[stateiso] compiling {src_c.name} -> {obj.name} (magic 0x{magic:08X})")
        subprocess.run(
            [
                str(CL6X),
                *CFLAGS,
                f"--define=STATEISO_MAGIC=0x{magic:08X}u",
                f"--define=STATEISO_AUDIO_FUNC={audio_func_name}",
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

    print("\n[stateiso] done")
    for out_zdl in outputs:
        print(f"  -> {out_zdl}")


if __name__ == "__main__":
    main()
