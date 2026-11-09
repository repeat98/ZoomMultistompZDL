"""Shared build for the zvis visual effects (Scope, Ring, Skull).

    from zvis_build import Canvas, raw, c_bytes, build
Each effect's build.py draws its static background (and any sprites), writes
a header with c_bytes(), then calls build(here, manifest, cover_rle).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (ROOT / "build", ROOT / "src" / "airwindows" / "common"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from linker import LinkerConfig, ObjFile, link, params_from_manifest  # noqa: E402
from screen_image import Canvas, encode_zoom_rle  # noqa: E402,F401
from stock_style_covers import round_shape, fill  # noqa: E402,F401
from zdl_size_guard import check as size_check  # noqa: E402
from make_em_thumbnails import render as em_thumbnail  # noqa: E402

TI_ROOT = Path("/Applications/ti/ti-cgt-c6000_8.5.0.LTS")
CFLAGS = ["--c99", "--opt_level=2", "--interrupt_threshold=1", "-mv6740", "--abi=eabi", "--mem_model:data=far",
          f"--include_path={TI_ROOT}/include", f"--include_path={ROOT}/src/airwindows/common",
          f"--include_path={HERE}"]
DSP_COST = 8.0          # real load ~600 cycles/callback average vs NAM ~15,000 (emulator)


def raw(c):
    """Canvas -> the pedal's picture layout: 8 row blocks x 128 columns, bit 0 on top."""
    out = bytearray(1024)
    for b in range(8):
        for x in range(128):
            v = 0
            for z in range(8):
                if c.pixels[b * 8 + z][x]:
                    v |= 1 << z
            out[b * 128 + x] = v
    return bytes(out)


def c_bytes(name, data, per_line=16):
    rows = [", ".join(f"0x{v:02X}" for v in data[i:i + per_line]) for i in range(0, len(data), per_line)]
    return f"static const unsigned char {name}[{len(data)}] = {{\n" + ",\n".join(rows) + "\n};\n"


def sprite(c, x0, y0, w, h):
    """A w x h region of a Canvas as zv_blit bits (row-major, MSB first)."""
    stride = (w + 7) // 8
    out = bytearray(stride * h)
    for r in range(h):
        for col in range(w):
            if c.pixels[y0 + r][x0 + col]:
                out[r * stride + col // 8] |= 0x80 >> (col % 8)
    return bytes(out)


def dials(c, labels=None):
    """Stock-style dial outlines under the firmware's knob boxes, and optional labels."""
    for x, label in zip((24, 65, 106), labels or (None, None, None)):
        if label:
            c.draw_text(label, x - (len(label) * 4 - 1) // 2, 38)
        round_shape(c, x, 53, 7)
        round_shape(c, x, 53, 5, 0)
        c.vline(x, 49, 53)


def build(here: Path, cover_rle: bytes) -> Path:
    """ZVIS_EMU=<dir>: build an emulator copy with -DZV_HOST (no firmware reads
    or calls, always 'visible') into <dir> instead of dist/."""
    import os
    m = json.loads((here / "manifest.json").read_text())
    name, audio = m["effect_name"], m["audio_func_name"]
    emu = os.environ.get("ZVIS_EMU")
    obj = here / f"{name.lower()}{'-emu' if emu else ''}.obj"
    subprocess.run([str(TI_ROOT / "bin/cl6x"), *CFLAGS, *(["--define=ZV_HOST"] if emu else []), "-c", str(here / f"{name.lower()}.c"), f"--output_file={obj}"],
                   check=True, cwd=here)
    for junk in ("compiler.opt", "linker.cmd"):
        (here / junk).unlink(missing_ok=True)
    o = ObjFile(obj)
    externals = {s['name'] for s in o.symbols if s['name'] and s['shndx'] == 0}
    assert externals <= {f"_{audio}_Info"}, f"unexpected externals {externals}"
    for sec in o.sections:
        if sec['name'] in ('.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
            assert sec['size'] == 0, f"unexpected {sec['name']} ({sec['size']} bytes)"
    audio_idx = next(s['idx'] for s in o.sections if s['name'] == '.audio')
    funcs = {s['name']: s['shndx'] for s in o.symbols if s['type'] == 2 and s['shndx']}
    # Knob-label callbacks (ZDL_GetLabel_*) are called by the pedal's UI, not by
    # the audio code, so they may sit in .text; branch labels the compiler emits
    # inside them ($C$L...) are local jumps there, not functions.
    label_secs = {i for n, i in funcs.items() if n.startswith('ZDL_GetLabel_')}
    stray = [n for n, i in funcs.items() if i != audio_idx and not n.startswith('ZDL_GetLabel_')
             and not (n.startswith('$C$') and i in label_secs)]
    assert not stray, f"functions outside .audio (a cross-section call froze the pedal): {stray}"
    out = (Path(emu) if emu else ROOT / "dist") / f"{name}.ZDL"
    link(LinkerConfig(effect_name=name, audio_func_name=audio, gid=m["gid"], fxid=m["fxid"],
                      params=params_from_manifest(m["params"]), obj_path=obj, output_path=out, screen_image=cover_rle,
                      fxid_version=m["fxid_version"].encode(), flags_byte=m["flags_byte"], materialize_init=True,
                      use_object_edit_handlers=False, synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                      knob3_blob_path=str(here / "unused"), dsp_cost=DSP_COST))
    size_check(out)
    if not emu:
        em_thumbnail(out)                      # same-name PNG: Effect Manager's thumbnail
    print(f"[{name.lower()}] -> {out}")
    return out
