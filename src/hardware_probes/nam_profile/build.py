#!/usr/bin/env python3
"""Build NAMProf (FXID 911): real-cycle and memory-placement profile of the
full-rate NAM kernel. Same capture and kernel header as NAMTime 0.01, so the
emulated reference (18,612 cycles/callback) applies directly. Outputs to
build/probes/nam-profile/, never dist/.
"""
import argparse, json, subprocess, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ap = argparse.ArgumentParser()
ap.add_argument('--header', type=Path, default=ROOT / 'build/probes/namlite/amptrec-audit/nam_kernel_pedal.h',
                help='kernel header to measure (default: the power-of-two TREC kernel NAMTime used)')
ap.add_argument('--name', default='NAMProf')
ap.add_argument('--fxid', type=int, default=911)
args = ap.parse_args()
OUT = ROOT / ('build/probes/nam-profile' + ('' if args.name == 'NAMProf' else '-' + args.name.lower()))
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'build'))
from linker import LinkerConfig, ObjFile, link, params_from_manifest
from capture_art import picture
from make_em_thumbnails import render

FXID, NAME, VERSION = args.fxid, args.name, b'0.01'

# The full-rate block kernel NAMTime measured. Private capture weights; the
# header must already exist from an amptrec audit build.
src = args.header
(OUT / 'nam_kernel_pedal.h').write_bytes(src.read_bytes())

# The production NAMLite wrapper, inlined as nam_core(). Built WITHOUT
# NAM_RATE_STEPS: this measures full rate, the thing we want to make fit.
core = (ROOT / 'src/hardware_probes/namlite/namlite.c').read_text()
for old, new in [('#pragma CODE_SECTION(Fx_FLT_NAMLite, ".audio")', '#pragma FUNC_ALWAYS_INLINE(nam_core)'),
                 ('void Fx_FLT_NAMLite(uintptr_t *ctx)', 'static inline void nam_core(uintptr_t *ctx)')]:
    assert old in core, f'namlite.c no longer contains: {old}'
    core = core.replace(old, new)
(OUT / 'measured_core.h').write_text(core)

ti = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
obj = OUT / 'profile.obj'
subprocess.run([str(ti / 'bin/cl6x'), '--c99', '-O2', '-mv6740', '--abi=eabi', '--mem_model:data=far',
                '--fp_mode=strict', '--fp_reassoc=off', f'--include_path={ti}/include',
                f'--include_path={OUT}', f'--include_path={ROOT}/src/airwindows/common',
                '--keep_asm', f'--asm_directory={OUT}', '-c', str(HERE / 'probe.c'),
                f'--output_file={obj}'], check=True)
o = ObjFile(obj)
assert not any(s['name'] and not s['shndx'] for s in o.symbols), 'unresolved helper symbol'
for sec in o.sections:
    if sec['name'] in ('.text', '.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
        assert not sec['size'], f"unexpected section {sec['name']}"

m = dict(effect_name=NAME, audio_func_name='Fx_FLT_NAMProf', gid=8, fxid=FXID,
         params=[dict(name='Input', max=100, default=44), dict(name='Output', max=100, default=27),
                 dict(name='Mix', max=100, default=100)])
for group in json.loads((ROOT / 'tools/effects_db.json').read_text()).values():
    if isinstance(group, list):
        assert not any(e.get('fxid') == FXID and e.get('gid') == 8 and e.get('name') != NAME for e in group), \
            f'FXID {FXID} is taken'
link(LinkerConfig(effect_name=NAME, audio_func_name=m['audio_func_name'], gid=8, fxid=FXID,
                  params=params_from_manifest(m['params']), obj_path=obj, output_path=OUT / f'{NAME}.ZDL',
                  fxid_version=VERSION, screen_image=picture('NAM'), materialize_init=True,
                  use_object_edit_handlers=False, synthesize_linesel_edit_handlers=True,
                  synth_edit_start_index=2, knob3_blob_path=str(OUT / 'unused')))
render(OUT / f'{NAME}.ZDL')
(OUT / 'manifest.json').write_text(json.dumps(m, indent=2) + '\n')
print(f'built {OUT / (NAME + ".ZDL")}')
