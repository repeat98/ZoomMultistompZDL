#!/usr/bin/env python3
"""Build ToTape9 diagnostic variants for hardware freeze isolation."""

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


def build_one(
    manifest: dict,
    obj: Path,
    *,
    effect_name: str,
    fxid: int,
    audio_nop: bool,
    use_object_edit_handlers: bool,
    object_edit_start_index: int = 0,
    use_air_knob3: bool = False,
    synthesize_linesel_edit_handlers: bool = False,
    synth_edit_start_index: int = 2,
) -> None:
    out_zdl = ROOT / "dist" / f"{effect_name}.ZDL"
    params = params_from_manifest(manifest["params"])
    cfg = LinkerConfig(
        effect_name=effect_name,
        audio_func_name=manifest["audio_func_name"],
        gid=manifest["gid"],
        fxid=fxid,
        params=params,
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        screen_image=make_airwindows_tape_screen(effect_name, ""),
        audio_nop=audio_nop,
        use_object_edit_handlers=use_object_edit_handlers,
        object_edit_start_index=object_edit_start_index,
        synthesize_linesel_edit_handlers=synthesize_linesel_edit_handlers,
        synth_edit_start_index=synth_edit_start_index,
        knob3_blob_path=None if use_air_knob3 else "/tmp/__nonexistent__",
    )
    print(
        f"\n[totape9 variants] {effect_name}: "
        f"audio_nop={audio_nop}, object_edit_handlers={use_object_edit_handlers}"
    )
    link(cfg)


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    src_c = HERE / "totape9.c"
    obj = HERE / "totape9.obj"
    tiny_src_c = HERE / "totape9_tiny.c"
    tiny_obj = HERE / "totape9_tiny.obj"
    (ROOT / "dist").mkdir(exist_ok=True)

    print(f"[totape9 variants] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )
    print(f"[totape9 variants] compiling {tiny_src_c.name} -> {tiny_obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(tiny_src_c), f"--output_file={tiny_obj}"],
        check=True,
        cwd=HERE,
    )

    # Flash order:
    # 1. T9NoAudio: metadata + 9 generated edit handlers, no DSP.
    # 2. T9NoHand: metadata + DSP, but no generated edit handlers.
    # 3. T9Meta: metadata only, no generated edit handlers and no DSP.
    build_one(
        manifest,
        obj,
        effect_name="T9NoAudio",
        fxid=0x01A0,
        audio_nop=True,
        use_object_edit_handlers=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9NoHand",
        fxid=0x01A1,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Stock3",
        fxid=0x01A5,
        audio_nop=False,
        use_object_edit_handlers=False,
        use_air_knob3=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Page2",
        fxid=0x01A6,
        audio_nop=False,
        use_object_edit_handlers=True,
        object_edit_start_index=3,
        use_air_knob3=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Synth",
        fxid=0x01A7,
        audio_nop=False,
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
    )
    tiny_manifest = dict(manifest)
    tiny_manifest["audio_func_name"] = "Fx_FLT_ToTape9_Tiny"
    build_one(
        tiny_manifest,
        tiny_obj,
        effect_name="T9Tiny",
        fxid=0x01A3,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    probe_manifest = dict(manifest)
    probe_manifest["audio_func_name"] = "Fx_FLT_ToTape9_ParamProbe"
    build_one(
        probe_manifest,
        tiny_obj,
        effect_name="T9Param",
        fxid=0x01A4,
        audio_nop=False,
        use_object_edit_handlers=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Meta",
        fxid=0x01A2,
        audio_nop=True,
        use_object_edit_handlers=False,
    )


if __name__ == "__main__":
    main()
