#!/usr/bin/env python3
"""Build the isolated NAMTest pass-through probe; no model included."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'build'))
from linker import LinkerConfig, link, params_from_manifest


def main():
    m = json.loads((HERE / 'manifest.json').read_text())
    out = ROOT / 'build' / 'probes' / 'namtest'
    out.mkdir(parents=True, exist_ok=True)
    obj = out / 'namtest.obj'
    compiler = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS/bin/cl6x')
    subprocess.run([str(compiler), '--c99', '-O2', '-mv6740', '--abi=eabi',
                    '--mem_model:data=far', f'--include_path={compiler.parent.parent / "include"}', '-c', str(HERE / 'namtest.c'),
                    f'--output_file={obj}'], cwd=out, check=True)
    link(LinkerConfig(
        effect_name=m['effect_name'], audio_func_name=m['audio_func_name'],
        gid=m['gid'], fxid=m['fxid'], params=params_from_manifest(m['params']),
        obj_path=obj, output_path=out / 'NAMTest.ZDL',
        fxid_version=m['fxid_version'].encode('ascii'), flags_byte=1,
        materialize_init=True, use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
        knob3_blob_path=str(out / 'unused-knob3.bin'),
    ))


if __name__ == '__main__':
    main()
