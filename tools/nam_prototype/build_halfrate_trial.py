#!/usr/bin/env python3
"""Build the half-rate A2 Lite trial; experimental, never published to dist.

WHY THIS EXISTS. NAMTime 0.01 reported code 5 on hardware -- the neural kernel
alone averages at or above a whole callback interval, leaving nothing for the
firmware or the other five slots. That is why the crackle worsens when other
effects are added, and why the full-rate scheduling screen could not fix it: its
best variant was 17,279 cycles against 18,612, a few percent where roughly 2x is
needed.

Running the network at 22.05 kHz halves the neural work exactly. The generated
kernel is left BYTE-IDENTICAL -- only the wrapper's feeding and reading change,
behind -DNAM_HALF_RATE in namlite.c -- so nothing about the tested numerics moves.

This is a sound-changing fallback, not a transparent optimization, and the docs
were right to insist on the distinction. Measured against full rate on the TREC
capture: <1k unchanged, 1-4k -2 to -4 dB, 4-8k -22 to -27 dB, and every time
constant in the capture doubles because the dilated receptive field is a fixed
number of samples. The owner compared host renders of both before this was built.

    python3 tools/nam_prototype/build_halfrate_trial.py <model.nam> \
        [--short-name amptrec] [--out DIR]
"""
from pathlib import Path
import argparse, json, re, subprocess, sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/nam_prototype'), str(ROOT / 'build')]
from generate_block import generate_block
import exact_rings
import tone_stack
from linker import LinkerConfig, ObjFile, link, params_from_manifest
from capture_art import picture

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('model', type=Path)
p.add_argument('--short-name', default='half',
               help='ASCII capture name, 1-8 letters/digits/hyphen/underscore')
p.add_argument('--out', type=Path)
p.add_argument('--steps', type=int, default=7, choices=[4,5,6,7,8],
               help='network steps per 8-sample callback; 8 = full rate')
p.add_argument('--exact-rings', action='store_true',
               help='size history rings exactly (bit-identical output, fits L2); see exact_rings.py')
p.add_argument('--interleave', action='store_true',
               help='with --exact-rings: store the 3 channels side by side (fewer cache lines per read)')
p.add_argument('--regacc', action='store_true',
               help='with --interleave: 8-sample tap loop with register accumulators (bit-identical, faster)')
p.add_argument('--tone-stack', action='store_true',
               help='add Bass/Mid/Treb (knobs 4-6), voiced like the NAM plugin; see tone_stack.py')
p.add_argument('--tone-half', action='store_true',
               help='with --tone-stack: 51-row tone table (even knobs), 3 KB smaller')
p.add_argument('--gate', action='store_true',
               help='with --tone-stack: add a noise gate (knob 7, 0 = off); see nam_gate.h')
p.add_argument('--cflag', action='append', default=[],
               help='extra cl6x flag (diagnostics only, e.g. --disable_software_pipelining)')
p.add_argument('--fxid', type=int, default=900)
p.add_argument('--eco-group', type=int, default=None, help='samples per register-accumulator group for the <8 block (default 4)')
p.add_argument('--dsp-cost', type=float, default=20.0, help='declared DSP cost (pedal budget ~230)')
p.add_argument('--version', default='0.17')
args = p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_-]{1,8}', args.short_name):
    p.error('short name must be 1-8 ASCII letters/digits/hyphens/underscores')

tag = (f'rate{args.steps}of8' + ('-exact' if args.exact_rings else '') + ('-il' if args.interleave else '')
       + ('-ra' if args.regacc else '') + ('-eq' if args.tone_stack else '') + ('-gate' if args.gate else '')  + ('-th' if args.tone_half else ''))
if args.gate and not args.tone_stack:
    p.error('--gate needs --tone-stack')
out = (args.out or ROOT / f'build/probes/namlite/{tag}').resolve()
generate_block(args.model, out)
if args.tone_stack:
    tone_stack.write_table(out, args.tone_half)
if args.exact_rings:
    s = exact_rings.apply(out, args.interleave, args.regacc, (args.steps,) if args.regacc and args.steps < 8 else (), args.eco_group)
    print(f"  exact rings: history {s['history_before']*4/1024:.1f} KB -> {s['history_after']*4/1024:.1f} KB")

ti = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
obj = out / 'namlite.obj'
subprocess.run([str(ti / 'bin/cl6x'), '--c99', '-O2', '-mv6740', '--abi=eabi',
                '--mem_model:data=far', '--fp_mode=strict', '--fp_reassoc=off',
                *([f'-DNAM_RATE_STEPS={args.steps}'] if args.steps < 8 else []),
                *(['-DNAM_TONE_STACK'] if args.tone_stack else []),
                *(['-DNAM_GATE'] if args.gate else []),
                *args.cflag,
                f'--include_path={ti}/include',
                f'--include_path={ROOT}/src/airwindows/common',
                f'--include_path={ROOT}/src/hardware_probes/namlite',
                f'--include_path={out}', '--keep_asm', f'--asm_directory={out}',
                '-c', str(ROOT / 'src/hardware_probes/namlite/namlite.c'),
                f'--output_file={obj}'], check=True, timeout=900)

o = ObjFile(obj)
# Same guards the other NAM builds use: no unresolved helper the loader cannot
# fix up, and nothing outside .audio. Both are documented freeze classes.
assert not any(v['name'] and not v['shndx'] for v in o.symbols), 'unresolved helper symbol'
for sec in o.sections:
    if sec['name'] in ('.text', '.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
        assert not sec['size'], f"unexpected section {sec['name']} ({sec['size']} bytes)"

m = json.loads((ROOT / 'src/hardware_probes/namlite/manifest.json').read_text())
dest = out / 'NAMLite.ZDL'
link(LinkerConfig(effect_name='NAMSlot1', audio_func_name=m['audio_func_name'],
                  gid=8, fxid=args.fxid, params=params_from_manifest(m['params'] + (
                      [dict(name='Bass', max=100, default=50), dict(name='Mid', max=100, default=50),
                       dict(name='Treb', max=100, default=50)] if args.tone_stack else [])
                      + ([dict(name='Gate', max=100, default=0)] if args.gate else [])),
                  obj_path=obj, output_path=dest,
                  fxid_version=args.version.encode('ascii'),
                  screen_image=picture('NAM'), materialize_init=True,
                  use_object_edit_handlers=False,
                  synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                  knob3_blob_path=str(out / 'unused'), dsp_cost=args.dsp_cost))

# Name-only metadata patch; coefficient and audio bytes are untouched.
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
z = Zdl.load(dest)
c = _read_elf_sections(z.elf)['.const']
base = 20 + z.header_size + c['offset']
data = bytearray(dest.read_bytes())
name = data.index(b'OnOff\0', base) + 48
assert data[name:name + 8] == b'NAMSlot1', 'display-name field not where expected'
data[name:name + 12] = ('NAM-' + args.short_name).encode().ljust(12, b'\0')
dest.write_bytes(data)

import hashlib
print(f"\n  {dest}  ({dest.stat().st_size} bytes)")
print(f"  sha256 {hashlib.sha256(dest.read_bytes()).hexdigest()}")
print(f"  fxid {args.fxid}  version {args.version}  pedal name NAM-{args.short_name}")
print(f"  rate {args.steps}/8 of full")
print("  EXPERIMENTAL -- not for dist. Hardware result pending.")
sys.path.insert(0, str(ROOT / 'build'))
from zdl_size_guard import sizes as _sizes, MAX_FILE, MAX_CODE_DATA
_n, _tc = _sizes(dest)
print(f'  size: {_n} bytes, code+data {_tc} (proven max {MAX_FILE} / {MAX_CODE_DATA})' + ('  ** OVER: froze the pedal before **' if _n > MAX_FILE or _tc > MAX_CODE_DATA else ''))
