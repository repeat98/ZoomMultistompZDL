import json,sys,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/slo-ir';sys.path.insert(0,str(ROOT/'build'))
from capture_art import picture
from linker import LinkerConfig,ObjFile,link,params_from_manifest
m=json.loads((HERE/'manifest.json').read_text());ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=OUT/'slo.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi','--mem_model:data=far',f'--include_path={ti}/include',f'--include_path={OUT}',f'--include_path={ROOT}/src/airwindows/common','--keep_asm',f'--asm_directory={OUT}','-c',str(HERE/'slo_ir.c'),f'--output_file={obj}'],check=True,cwd=OUT)
o=ObjFile(obj);print('UNDEFINED',[s['name'] for s in o.symbols if s['name'] and not s['shndx']]);print('AUDIO',o.get_section('.audio')['size'])
assert not any(s['name'] and not s['shndx'] for s in o.symbols)
for s in o.sections:
 if s['name'] in ('.text','.bss','.far','.fardata') or s['name'].startswith('.switch'):assert not s['size'],s['name']
assert o.get_section('.audio')['size']<18000
link(LinkerConfig(effect_name=m['effect_name'],audio_func_name=m['audio_func_name'],gid=m['gid'],fxid=m['fxid'],params=params_from_manifest(m['params']),obj_path=obj,output_path=OUT/'SloIR.ZDL',fxid_version=b'0.01',screen_image=picture('IR'),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(OUT/'unused')))
