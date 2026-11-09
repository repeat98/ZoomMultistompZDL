#!/usr/bin/env python3
"""Build a separate full-rate capture-slot-1 timing trial; no converter changes."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'build'))
from generate_block import generate_block
from linker import LinkerConfig,link,params_from_manifest,ObjFile
from capture_art import picture
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('out',type=Path);a=p.parse_args();out=a.out.resolve()
generate_block(a.model,out,inner_unroll=2)
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=out/'namlite.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi','--mem_model:data=far','--fp_mode=strict','--fp_reassoc=off',f'--include_path={ti}/include',f'--include_path={ROOT}/src/airwindows/common',f'--include_path={out}','--keep_asm',f'--asm_directory={out}','-c',str(ROOT/'src/hardware_probes/namlite/namlite.c'),f'--output_file={obj}'],check=True)
o=ObjFile(obj);assert not any(s['name'] and s['shndx']==0 for s in o.symbols)
for s in o.sections:
 if s['name'] in ('.text','.bss','.far','.fardata') or s['name'].startswith('.switch'):assert s['size']==0
m=json.loads((ROOT/'src/hardware_probes/namlite/manifest.json').read_text());dest=out/'NAMLite.ZDL'
link(LinkerConfig(effect_name='NAMSlot1',audio_func_name=m['audio_func_name'],gid=8,fxid=900,params=params_from_manifest(m['params']),obj_path=obj,output_path=dest,fxid_version=b'0.15',screen_image=picture('NAM'),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(out/'unused')))
z=Zdl.load(dest);c=_read_elf_sections(z.elf)['.const'];base=20+z.header_size+c['offset'];d=bytearray(dest.read_bytes());name=d.index(b'OnOff\0',base)+48
assert d[name:name+8]==b'NAMSlot1';d[name:name+12]=b'NAM-amptrec'.ljust(12,b'\0');dest.write_bytes(d)
print('Trial only: capture slot 1, full-rate DSP, version 0.15. Converter unchanged.')
