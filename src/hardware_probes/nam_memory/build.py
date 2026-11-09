import json,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/nam-memory';OUT.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(ROOT/'build'))
from linker import LinkerConfig,ObjFile,link,params_from_manifest
from capture_art import draw
from screen_image import encode_zoom_rle
from stock_style_covers import fill,round_shape
from make_em_thumbnails import render
m=dict(effect_name='NAMMem',audio_func_name='Fx_FLT_NAMMem',gid=8,fxid=909,params=[dict(name='Test',max=1,default=1)])
db=json.loads((ROOT/'tools/effects_db.json').read_text())
for group in db.values():
 if isinstance(group,list):assert not any(e.get('fxid')==909 and e.get('gid')==8 and e.get('name')!='NAMMem' for e in group)
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=OUT/'probe.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi','--mem_model:data=far',f'--include_path={ti}/include','--keep_asm',f'--asm_directory={OUT}','-c',str(HERE/'probe.c'),f'--output_file={obj}'],check=True)
o=ObjFile(obj);assert not any(s['name'] and not s['shndx'] for s in o.symbols)
for s in o.sections:
 if s['name'] in ('.text','.bss','.far','.fardata') or s['name'].startswith('.switch'):assert not s['size']
canvas=draw('NAM');fill(canvas,3,35,124,62,0);canvas.draw_text('TEST',57,37);round_shape(canvas,64,53,7);round_shape(canvas,64,53,5,0);canvas.vline(64,49,53)
link(LinkerConfig(effect_name=m['effect_name'],audio_func_name=m['audio_func_name'],gid=8,fxid=909,params=params_from_manifest(m['params']),obj_path=obj,output_path=OUT/'NAMMem.ZDL',fxid_version=b'0.02',screen_image=encode_zoom_rle(canvas),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(OUT/'unused')))
render(OUT/'NAMMem.ZDL');(OUT/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
