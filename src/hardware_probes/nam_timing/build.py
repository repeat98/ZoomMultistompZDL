import json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/nam-timing';OUT.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(ROOT/'build'))
from linker import LinkerConfig,ObjFile,link,params_from_manifest
from capture_art import picture
from make_em_thumbnails import render
src=ROOT/'build/probes/namlite/amptrec-audit/nam_kernel_pedal.h'
(OUT/'nam_kernel_pedal.h').write_bytes(src.read_bytes())
s=(ROOT/'src/hardware_probes/namlite/namlite.c').read_text().replace('#pragma CODE_SECTION(Fx_FLT_NAMLite, ".audio")','#pragma FUNC_ALWAYS_INLINE(nam_core)').replace('void Fx_FLT_NAMLite(uintptr_t *ctx)','static inline void nam_core(uintptr_t *ctx)')
(OUT/'measured_core.h').write_text(s)
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=OUT/'timing.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi','--mem_model:data=far','--fp_mode=strict','--fp_reassoc=off',f'--include_path={ti}/include',f'--include_path={OUT}',f'--include_path={ROOT}/src/airwindows/common','--keep_asm',f'--asm_directory={OUT}','-c',str(HERE/'probe.c'),f'--output_file={obj}'],check=True)
o=ObjFile(obj);assert not any(s['name'] and not s['shndx'] for s in o.symbols)
for sec in o.sections:
 if sec['name'] in ('.text','.bss','.far','.fardata') or sec['name'].startswith('.switch'):assert not sec['size']
m=dict(effect_name='NAMTime',audio_func_name='Fx_FLT_NAMTime',gid=8,fxid=910,params=[dict(name='Input',max=100,default=44),dict(name='Output',max=100,default=27),dict(name='Mix',max=100,default=100)])
for group in json.loads((ROOT/'tools/effects_db.json').read_text()).values():
 if isinstance(group,list):assert not any(e.get('fxid')==910 and e.get('gid')==8 and e.get('name')!='NAMTime' for e in group)
link(LinkerConfig(effect_name='NAMTime',audio_func_name='Fx_FLT_NAMTime',gid=8,fxid=910,params=params_from_manifest(m['params']),obj_path=obj,output_path=OUT/'NAMTime.ZDL',fxid_version=b'0.01',screen_image=picture('NAM'),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(OUT/'unused')))
render(OUT/'NAMTime.ZDL');(OUT/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
