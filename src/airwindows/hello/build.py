#!/usr/bin/env python3
"""Build HELLO.ZDL from hello.c + manifest.json.

Now using the linker to test the 3-param rendering bug with a minimal DSP.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent      # src/airwindows/hello/build.py → repo root
sys.path.insert(0, str(ROOT / "build"))

from linker import LinkerConfig, Param, link  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X    = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    "--opt_for_space=3",
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())

    src_c   = HERE / "hello.c"
    obj     = HERE / "hello.obj"
    out_zdl = ROOT / "dist" / f"{manifest['effect_name']}.ZDL"
    out_zdl.parent.mkdir(exist_ok=True)

    print(f"[hello] compiling {src_c.name} → {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )

    cfg = LinkerConfig(
        effect_name = manifest["effect_name"],
        gid         = manifest["gid"],
        fxid        = manifest["fxid"],
        params      = [Param(p["name"], p["max"], p["default"]) for p in manifest["params"]],
        obj_path    = obj,
        output_path = out_zdl,
        fxid_version= manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte  = manifest.get("flags_byte", 0x01),
        audio_nop   = manifest.get("audio_nop", False),
        # Force NOP_RETURN for knob3 — AIR mix_edit blob crashes when
        # invoked outside AIR's context (verified). Use this build to
        # isolate the "knob body missing" rendering issue without the
        # interaction freeze masking it. Once the rendering is fixed,
        # we'll need a real working knob3 handler.
        knob3_blob_path = "/tmp/__nonexistent__",
    )
    link(cfg)

    print(f"\n[hello] done → {out_zdl}")


if __name__ == "__main__":
    main()
