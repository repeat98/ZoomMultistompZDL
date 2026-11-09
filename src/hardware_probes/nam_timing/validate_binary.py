#!/usr/bin/env python3
"""Audit NAM ZDL tables, runtime address relocations, and parameter init."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'build'))
from zdl import Zdl
from linker import ObjFile,_init_materialize_body
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl
p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
p.add_argument('--delay-samples',type=int)
p.add_argument('--fxid',type=int,default=910)
a=p.parse_args();b=a.build
path=b/'NAMTime.ZDL';z=Zdl.load(path);d=z.elf;s=_read_elf_sections(d)
o=ObjFile(b/'timing.obj');audio=o.get_section('.audio')
c=s['.const'];t=s['.text'];r=s['.rela.dyn'];sy=s['.dynsym']
cd=d[c['offset']:c['offset']+c['size']]
for sec in o.sections:
 if sec['name'].startswith('.const:'):assert bytes(sec['data']) in cd,sec['name']
targets=[]
for at in range(r['offset'],r['offset']+r['size'],12):
 off,info,add=struct.unpack_from('<IIi',d,at)
 if t['addr']<=off<t['addr']+audio['size']:
  target=struct.unpack_from('<I',d,sy['offset']+(info>>8)*16+4)[0]+add
  typ=info&255;assert typ in (9,10)
  assert c['addr']<=target<c['addr']+c['size']
  word=struct.unpack_from('<I',d,t['offset']+off-t['addr'])[0]
  assert (word>>7)&65535==((target if typ==9 else target>>16)&65535)
  targets.append(target)
assert len(targets)==len(o.relocs[audio['idx']])
base=cd.index(b'OnOff\0');handlers=[]
for i in range(3):handlers.append(struct.unpack_from('<I',cd,base+(i+2)*48+28)[0])
init=struct.unpack_from('<I',cd,base+48+28)[0]
body=_init_materialize_body(handlers,init);at=t['offset']+init-t['addr']
assert d[at:at+len(body)]==body
effect=parse_zdl(path);assert effect['fxid']==a.fxid and effect['gid']==8
assert [(p['name'],p['max'],p['default']) for p in effect['params']]==[('Input',100,44),('Output',100,27),('Mix',100,100)]
report={'version':z.info.fx_version.decode().rstrip('\0'),'bytes':path.stat().st_size,
 'audio_bytes':audio['size'],'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
 'table_relocations':len(targets),'checks':['exact constant tables','runtime address instruction halves/targets','parameter init bytes','unchanged ID and controls'],
 'hardware':'pending'}
if a.delay_samples is not None:report['delay_samples']=a.delay_samples
(b/'binary-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
