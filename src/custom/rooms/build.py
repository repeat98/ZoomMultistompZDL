#!/usr/bin/env python3
"""Build Rooms.ZDL from rooms.c + manifest_pedal.json (5-knob pedal build).

Death By Audio Rooms-inspired multi-mode reverberator. Reads manifest_pedal.json.
Requires the TI C6000 compiler at TI_ROOT below. Run from repo root:
    python3 build_all.py rooms
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "src" / "airwindows" / "common"))

from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
from manifest_params import write_param_header  # noqa: E402
from stock_style_covers import POSITIONS
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist",
                        help="destination for an isolated hardware-test build")
    parser.add_argument("--materialize-init", action=argparse.BooleanOptionalAction, default=True,
                        help="enable the corrected init for hardware validation")
    parser.add_argument("--discrete-mode-pilot", action="store_true",
                        help="build separate Rooms6 probe with six Mode positions")
    args = parser.parse_args()
    manifest = json.loads((HERE / "manifest_pedal.json").read_text())
    if args.discrete_mode_pilot:
        manifest.update(effect_name="Rooms6", fxid=490, fxid_version="0.01")
        manifest["params"][0].update(max=5, default=0)
        args.output_dir = ROOT / "build" / "probes"
        os.environ["ZDL_SELECTOR_LABELS"] = "1"
    write_param_header(manifest, HERE / "rooms_params.h", "ROOMS")

    src_c = HERE / "rooms.c"
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    effect_name = manifest["effect_name"]
    audio_func = manifest["audio_func_name"]
    obj = HERE / f"{effect_name.lower()}.obj"
    out_zdl = out_dir / f"{effect_name}.ZDL"

    print(f"[rooms] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            *(["--define=ROOMS_DISCRETE_MODE=1"] if args.discrete_mode_pilot else []),
            f"--define=ROOMS_AUDIO_FUNC={audio_func}",
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
        screen_image=make_cover("Rooms", [p["name"] for p in manifest["params"]]),
        audio_func_name=audio_func,
        gid=manifest["gid"],
        fxid=manifest["fxid"],
        params=params_from_manifest(manifest["params"]),
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        audio_nop=manifest.get("audio_nop", False),
        knob_positions=POSITIONS["Rooms"],
        materialize_init=args.materialize_init,
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
        knob3_blob_path="/tmp/__nonexistent__",
    )
    link(cfg)

    print(f"\n[rooms] done -> {out_zdl}")


if __name__ == "__main__":
    main()
