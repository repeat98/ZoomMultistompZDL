#!/usr/bin/env python3
"""Build NAMLite from an external A2 Lite model, outside release dist."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT/'build'), str(ROOT/'tools/nam_prototype')]
from generate import generate
from capture_art import picture
from linker import LinkerConfig, ObjFile, link, params_from_manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('model', type=Path)
    args = p.parse_args()
    out = ROOT/'build/probes/namlite'
    out.mkdir(parents=True, exist_ok=True)
    (out/'THIRD-PARTY-NOTICES.txt').write_text((HERE/'THIRD-PARTY-NOTICES.txt').read_text())
    m = json.loads((HERE/'manifest.json').read_text())
    generate(args.model, out)
    # One audio entry only. Do not ship out-of-line kernel helpers.
    lines = []
    for line in (out/'nam_kernel.c').read_text().splitlines():
        if line.startswith(('unsigned nam_state_bytes(', 'void nam_reset(', 'void nam_process(')):
            continue
        if line.startswith('static void layer_'):
            name = line.split('(')[0].split()[-1]
            lines.append(f'#pragma FUNC_ALWAYS_INLINE({name})')
            line = line.replace('static void ', 'static inline void ', 1)
        if line.startswith('float nam_sample('):
            lines.append('#pragma FUNC_ALWAYS_INLINE(nam_sample)')
            line = 'static inline ' + line
        lines.append(line)
    (out/'nam_kernel_pedal.h').write_text('\n'.join(lines)+'\n')
    ti = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
    obj = out/'namlite.obj'
    subprocess.run([str(ti/'bin/cl6x'), '--c99', '-O2', '-mv6740', '--abi=eabi',
                    '--mem_model:data=far', f'--include_path={ti}/include',
                    f'--include_path={ROOT}/src/airwindows/common', f'--include_path={out}',
                    '--keep_asm', f'--asm_directory={out}', '-c', str(HERE/'namlite.c'),
                    f'--output_file={obj}'], cwd=out, check=True)
    parsed = ObjFile(obj)
    assert not any(s['name'] and s['shndx'] == 0 for s in parsed.symbols), 'Unexpected helper symbol'
    for sec in parsed.sections:
        if sec['name'] in ('.text', '.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
            assert sec['size'] == 0, f"Unexpected section {sec['name']}"
    entry = next(s for s in parsed.symbols if s['name'] == m['audio_func_name'])
    assert entry['value'] == 0, 'Linker requires audio entry at section start'
    link(LinkerConfig(effect_name=m['effect_name'], audio_func_name=m['audio_func_name'],
        gid=m['gid'], fxid=m['fxid'], params=params_from_manifest(m['params']),
        obj_path=obj, output_path=out/'NAMLite.ZDL', fxid_version=m['fxid_version'].encode('ascii'),
        screen_image=picture('NAM'), materialize_init=True, use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
        knob3_blob_path=str(out/'unused-knob3.bin')))


if __name__ == '__main__':
    main()
