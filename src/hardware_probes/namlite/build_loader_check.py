#!/usr/bin/env python3
"""Build small NAMLite 0.03 loader check, preserving the neural build separately."""
import json
import subprocess
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'build'))
from linker import LinkerConfig,link,params_from_manifest
m=json.loads((HERE/'manifest.json').read_text())
out=ROOT/'build/probes/namlite/loader-check'
out.mkdir(parents=True,exist_ok=True)
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
obj=out/'loader_check.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi',
    '--mem_model:data=far',f'--include_path={ti}/include',
    f'--include_path={ROOT}/src/airwindows/common','-c',str(HERE/'loader_check.c'),
    f'--output_file={obj}'],cwd=out,check=True)
link(LinkerConfig(effect_name=m['effect_name'],audio_func_name=m['audio_func_name'],
    gid=m['gid'],fxid=m['fxid'],params=params_from_manifest(m['params']),
    obj_path=obj,output_path=out/'NAMLite.ZDL',fxid_version=b'0.03',
    materialize_init=True,use_object_edit_handlers=False,
    synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,
    knob3_blob_path=str(out/'unused-knob3.bin')))
