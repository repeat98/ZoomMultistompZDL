import hashlib,json,struct,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/slo-ir';sys.path.insert(0,str(ROOT/'build'))
from zdl import Zdl
from linker import ObjFile,_init_materialize_body
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl
p=OUT/'SloIR.ZDL';z=Zdl.load(p);d=z.elf;s=_read_elf_sections(d);o=ObjFile(OUT/'slo.obj');c=s['.const'];t=s['.text'];r=s['.rela.dyn'];sy=s['.dynsym'];cd=d[c['offset']:c['offset']+c['size']]
for sec in o.sections:
 if sec['name'].startswith('.const:'):assert bytes(sec['data']) in cd,sec['name']
count=0
for at in range(r['offset'],r['offset']+r['size'],12):
 off,info,add=struct.unpack_from('<IIi',d,at)
 if t['addr']<=off<t['addr']+o.get_section('.audio')['size']:
  target=struct.unpack_from('<I',d,sy['offset']+(info>>8)*16+4)[0]+add;typ=info&255;assert typ in (9,10)
  assert c['addr']<=target<c['addr']+c['size'];word=struct.unpack_from('<I',d,t['offset']+off-t['addr'])[0]
  assert (word>>7)&65535==((target if typ==9 else target>>16)&65535);count+=1
base=cd.index(b'OnOff\0');handlers=[struct.unpack_from('<I',cd,base+(i+2)*48+28)[0] for i in range(3)];init=struct.unpack_from('<I',cd,base+48+28)[0];body=_init_materialize_body(handlers,init);at=t['offset']+init-t['addr'];assert d[at:at+len(body)]==body
entry=parse_zdl(p);assert entry['fxid']==908 and entry['gid']==8
for group in json.loads((ROOT/'tools/effects_db.json').read_text()).values():
 if isinstance(group,list):assert not any(e.get('fxid')==908 and e['name']!='SloIR' for e in group)
report=dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),audio_bytes=o.get_section('.audio')['size'],constant_relocations=count,hardware='pending',checks=['coefficient tables exact','large constant addresses and split instructions','descriptor initialization','ID uniqueness'])
(OUT/'binary-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
