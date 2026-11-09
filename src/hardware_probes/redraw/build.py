#!/usr/bin/env python3
"""Build the Redraw probe (test A, docs/pedal-research/animated-covers.md) into dist/Redraw.ZDL."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "src" / "airwindows" / "common"))

from linker import LinkerConfig, ObjFile, link, params_from_manifest  # noqa: E402
from zdl_size_guard import check as size_check  # noqa: E402

TI_ROOT = Path("/Applications/ti/ti-cgt-c6000_8.5.0.LTS")
CFLAGS = ["--c99", "--opt_level=2", "-mv6740", "--abi=eabi", "--mem_model:data=far", f"--include_path={TI_ROOT}/include"]


def main() -> None:
    m = json.loads((HERE / "manifest.json").read_text())
    obj = HERE / "redraw.obj"
    subprocess.run([str(TI_ROOT / "bin/cl6x"), *CFLAGS, "-c", str(HERE / "redraw.c"), f"--output_file={obj}"],
                   check=True, cwd=HERE)
    for junk in ("compiler.opt", "linker.cmd"):
        (HERE / junk).unlink(missing_ok=True)
    o = ObjFile(obj)
    assert not any(s['name'] and s['shndx'] == 0 for s in o.symbols), 'unexpected external helper'
    for sec in o.sections:
        if sec['name'] in ('.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
            assert sec['size'] == 0, f"unexpected writable data in {sec['name']}"
    out = ROOT / "dist" / f"{m['effect_name']}.ZDL"
    link(LinkerConfig(effect_name=m["effect_name"], audio_func_name=m["audio_func_name"], gid=m["gid"], fxid=m["fxid"],
                      params=params_from_manifest(m["params"]), obj_path=obj, output_path=out,
                      fxid_version=m["fxid_version"].encode(), flags_byte=m["flags_byte"], materialize_init=True,
                      use_object_edit_handlers=False, synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                      knob3_blob_path=str(HERE / "unused")))
    size_check(out)
    print(f"[redraw] -> {out}")


if __name__ == "__main__":
    main()
