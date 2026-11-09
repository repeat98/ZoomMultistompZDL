#!/usr/bin/env python3
"""Build compact NAMLite from a compatible external capture; no dist writes."""
import argparse,json,re,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path[:0]=[str(ROOT/'build'),str(ROOT/'tools/nam_prototype')]
from generate_compact import compact
from linker import LinkerConfig,ObjFile,link,params_from_manifest

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'build/probes/namlite/compact')
    p.add_argument('--version',default='0.06')
    p.add_argument('--block',action='store_true',help='Use layer-major block processing')
    a=p.parse_args()
    if not re.fullmatch(r'[0-9]\.[0-9]{2}',a.version):p.error('Version must have the form 0.08')
    out=a.output.resolve()
    if a.block:
        from generate_block import generate_block
        generate_block(a.model,out)
    else:compact(a.model,out)
    m=json.loads((HERE/'manifest.json').read_text());ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=out/'namlite.obj'
    subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi',
        '--fp_mode=strict','--fp_reassoc=off',
        '--mem_model:data=far',f'--include_path={ti}/include',f'--include_path={out}',
        f'--include_path={ROOT}/src/airwindows/common','--keep_asm',f'--asm_directory={out}',
        '-c',str(HERE/'namlite.c'),f'--output_file={obj}'],cwd=out,check=True)
    o=ObjFile(obj)
    assert not any(s['name'] and s['shndx']==0 for s in o.symbols),'Unexpected helpers'
    for s in o.sections:
        if s['name'] in ('.text','.bss','.far','.fardata') or s['name'].startswith('.switch'):
            assert s['size']==0,s['name']
    assert next(s for s in o.symbols if s['name']==m['audio_func_name'])['value']==0
    assert o.get_section('.audio')['size']<18000,'Compact code exceeded stock envelope'
    link(LinkerConfig(effect_name=m['effect_name'],audio_func_name=m['audio_func_name'],
        gid=m['gid'],fxid=m['fxid'],params=params_from_manifest(m['params']),
        obj_path=obj,output_path=out/'NAMLite.ZDL',fxid_version=a.version.encode('ascii'),
        materialize_init=True,use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,
        knob3_blob_path=str(out/'unused-knob3.bin')))

if __name__=='__main__':main()
