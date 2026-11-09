"""Check opt-in label callbacks and normal parameter/init ABI in pilot ZDLs."""
import json,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'build'))
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
from linker import _init_materialize_body
from extract_effect_db import parse_zdl
from selector_metadata import pedal_label,SELECTORS

def verify_string_relocations(blob, sections, choices):
    # A descriptor callback pointer alone is insufficient: every string's
    # address materialization must also be relocated by the pedal loader.
    t=sections['.text']; c=sections['.const']; r=sections['.rela.dyn']; sy=sections['.dynsym']
    targets={}
    for j in range(r['offset'],r['offset']+r['size'],12):
        va,info,addend=struct.unpack_from('<IIi',blob,j)
        if info&255 not in (9,10) or not t['addr']<=va<t['addr']+t['size']:continue
        symidx=info>>8
        assert symidx>0, 'unresolved dynamic relocation'
        target=struct.unpack_from('<I',blob,sy['offset']+symidx*16+4)[0]+addend
        if c['addr']<=target<c['addr']+c['size']:
            off=c['offset']+target-c['addr']
            label=blob[off:off+8].split(b'\0')[0].decode('ascii',errors='replace')
            targets.setdefault(label,set()).add(info&255)
    for label in {pedal_label(g['label']) for cs in choices.values() for g in cs}:
        assert targets.get(label)=={9,10}, f'{label}: missing runtime string address relocation'

def verify():
 rows=[]
 for path in sorted((ROOT/'build/selector-pilot').glob('*.ZDL')):
  if path.stem == 'Rooms6': continue  # separate-ID probe, not a release ABI comparison
  blob=Zdl.load(path).elf;s=_read_elf_sections(blob);t=s['.text'];c=s['.const']
  cd=blob[c['offset']:c['offset']+c['size']];off=cd.index(b'OnOff\0')
  parsed=parse_zdl(path);release=parse_zdl(ROOT/'dist'/path.name)
  assert parsed==release, f'{path}: patch ABI changed'
  rd=s['.rela.dyn'];relocs={struct.unpack_from('<I',blob,j)[0] for j in range(rd['offset'],rd['offset']+rd['size'],12)}
  expected=SELECTORS[parsed['name']];labels=[];handlers=[]
  verify_string_relocations(blob,s,expected)
  for i,p in enumerate(parsed['params']):
   e=off+(i+2)*48;va=struct.unpack_from('<I',cd,e+36)[0]
   if p['name'] in expected:
    assert t['addr']<=va<t['addr']+t['size'],path
    assert c['addr']+e+36 in relocs,path
    labels.append(p['name'])
   else:assert va==0,path
   handlers.append(struct.unpack_from('<I',cd,e+28)[0])
  init=struct.unpack_from('<I',cd,off+48+28)[0];body=_init_materialize_body(handlers,init)
  start=t['offset']+init-t['addr'];assert blob[start:start+len(body)]==body,path
  rows.append({'effect':parsed['name'],'labels':labels,'patch_abi':'unchanged','init':'verified','hardware':'not tested'})
 assert len(rows)==6
 return rows
if __name__=='__main__':print(json.dumps(verify(),indent=2))
