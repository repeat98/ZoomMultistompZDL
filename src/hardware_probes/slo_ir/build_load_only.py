"""Build and audit the large-bank, dry-through IR diagnostic, outside dist."""
import hashlib,json,struct,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
BASE=ROOT/'build/probes/slo-ir'
OUT=BASE/'load-only-0.02'
OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'build'))
from capture_art import picture
from linker import LinkerConfig,ObjFile,link,params_from_manifest,_init_materialize_body
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl
from make_em_thumbnails import render
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
obj=OUT/'load_only.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi',
 '--mem_model:data=far',f'--include_path={ti}/include',f'--include_path={BASE}',
 '--keep_asm',f'--asm_directory={OUT}','-c',str(HERE/'load_only.c'),
 f'--output_file={obj}'],check=True)
o=ObjFile(obj);original=ObjFile(BASE/'slo.obj')
assert not any(s['name'] and not s['shndx'] for s in o.symbols)
assert o.get_section('.audio')['size']<128
assert not o.relocs.get(o.get_section('.audio')['idx'])
for s in o.sections:
 if s['name'] in ('.text','.bss','.far','.fardata') or s['name'].startswith('.switch'):
  assert not s['size']
tables=[s for s in original.sections if s['name'].startswith('.const:')]
assert len(tables)==5
for s in tables:
 assert bytes(o.get_section(s['name'])['data'])==bytes(s['data']),s['name']
m=json.loads((HERE/'manifest.json').read_text());p=OUT/'SloIR.ZDL'
link(LinkerConfig(effect_name='SloIR',audio_func_name=m['audio_func_name'],
 gid=8,fxid=908,params=params_from_manifest(m['params']),obj_path=obj,output_path=p,
 fxid_version=b'0.02',screen_image=picture('IR'),materialize_init=True,
 use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,
 synth_edit_start_index=2,knob3_blob_path=str(OUT/'unused')))
z=Zdl.load(p);secs=_read_elf_sections(z.elf);c=secs['.const'];t=secs['.text']
cd=z.elf[c['offset']:c['offset']+c['size']]
for s in tables:assert bytes(s['data']) in cd
failed=Zdl.load(BASE/'failed-0.01/SloIR.ZDL');fc=_read_elf_sections(failed.elf)['.const']
assert c['size']==fc['size'], 'Large bank or descriptor layout changed'
assert parse_zdl(p)['fxid']==908
start=cd.index(b'OnOff\0');handlers=[struct.unpack_from('<I',cd,start+(i+2)*48+28)[0] for i in range(3)]
init=struct.unpack_from('<I',cd,start+48+28)[0];body=_init_materialize_body(handlers,init)
at=t['offset']+init-t['addr'];assert z.elf[at:at+len(body)]==body
render(p)
report=dict(version='0.02',purpose='Large-bank load diagnostic; dry-through only',
 bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
 audio_bytes=o.get_section('.audio')['size'],constant_section_bytes=c['size'],
 coefficient_tables=len(tables),coefficient_bytes=sum(s['size'] for s in tables),
 checks=['same constant section size as failing build','all coefficient tables byte-exact',
 'audio has no relocations/helpers/state/buffer processing','descriptor init verified'],
 hardware='pending',interpretation='Success isolates loading but does not distinguish DSP cost from state initialization or coefficient-access faults in the full engine.')
(OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
