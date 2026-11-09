#!/usr/bin/env python3
"""Package eight distinct NAM identities with the tested 0.12 DSP, no captures."""
# SUPERSEDED 2026-09-28 by package_eq_templates.py (engine 0.21). This script
# rebuilds the loader templates from the 0.12 engine, which crackles at full
# rate -- running it would silently put that engine back into the NAM Loader.
# Kept for the record; it refuses to run without --legacy. The 0.14 templates it
# produced are archived in build/nam-archive/2026-09-28/nam_template-0.14/.
import sys as _sys
if '--legacy' not in _sys.argv:
    _sys.exit('package_multi_templates.py is superseded: use tools/nam_prototype/package_eq_templates.py '
              '(pass --legacy to rebuild the old 0.12-engine templates on purpose)')
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'build'))
from linker import LinkerConfig,link,params_from_manifest
from zdl import Zdl
from capture_art import picture as capture_picture
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl, _cover_b64
obj=ROOT/'build/probes/namlite/smokey-0.12/namlite.obj'
source=ROOT/'build/probes/namlite/smokey-0.12/NAMLite.ZDL'
assert hashlib.sha256(source.read_bytes()).hexdigest()=='06677004a5ea0a22114c6ba8ac4b0a9e09b38e3f966452f0721d3e978ab2e7ac'
base=Zdl.load(source);secs=_read_elf_sections(base.elf);c=secs['.const'];const=base.elf[c['offset']:c['offset']+c['size']];picture=capture_picture("NAM")
m=json.loads((ROOT/'src/hardware_probes/namlite/manifest.json').read_text())
out=ROOT/'tools/nam_template';db=json.loads((ROOT/'tools/effects_db.json').read_text())
used={e['fxid'] for group in db.values() if isinstance(group,list) for e in group if 'fxid'in e and not e.get('namSlot')}
entries=[];templates=[]
for i in range(8):
 fxid=900+i;assert fxid not in used
 p=out/f'slot-{i+1}.bin'
 link(LinkerConfig(effect_name=f'NAMSlot{i+1}',audio_func_name=m['audio_func_name'],gid=8,fxid=fxid,params=params_from_manifest(m['params']),obj_path=obj,output_path=p,fxid_version=b'0.14',screen_image=picture,materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(out/'unused')))
 z=Zdl.load(p);s=_read_elf_sections(z.elf);cs=s['.const'];offset=20+z.header_size+cs['offset'];data=bytearray(p.read_bytes());weights=data.index(const[0x2c0:0x2c0+1871*4],offset)
 assert data[weights:weights+1871*4]==const[0x2c0:0x2c0+1871*4]
 desc=z.elf[cs['offset']:cs['offset']+cs['size']].index(b'OnOff\0')+offset+48
 assert data[desc:desc+8]==f'NAMSlot{i+1}'.encode()
 # Verify all audio bytes are unchanged, not merely equal section lengths.
 t=s['.text'];old=secs['.text'];assert t['size']==old['size']  # Same object; constant-address operands move with art.
 from verify_capture_art import verify_audio
 verify_audio(base,z,5344)
 entry=parse_zdl(p);entry['cover']=_cover_b64(p);entry['namSlot']=i+1;entry['name']=f'NAMLite — capture {i+1}';entries.append(entry)
 data[weights:weights+1871*4]=bytes(1871*4);p.write_bytes(data)
 templates.append(dict(slot=i+1,fxid=fxid,id=entry['id'],file=p.name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),weights_offset=weights,name_offset=desc))
manifest=dict(format=2,engine='Tested NAMLite 0.12 block DSP; separate capture identities',weights_count=1871,version_offset=68,output_version='0.14',sample_rate=44100,slots=templates)
(out/'multi.json').write_text(json.dumps(manifest,indent=2)+'\n')
# Reserve all eight IDs in PE even if another browser created the files.
db['custom']=[e for e in db['custom'] if not e.get('namSlot')]+entries
from nam_capture_names import apply_local_names
apply_local_names(db['custom'],ROOT)
serialized=json.dumps(db,indent=1);(ROOT/'tools/effects_db.json').write_text(serialized+'\n')
p=ROOT/'tools/patch_editor.html';html=p.read_text();start=html.index('const DB=')+9;end=html.index('\n// Names follow',start) if '\n// Names follow' in html[start:] else html.index('\nconst BYID',start);tail=html[start:end];stop=tail.rfind(';');assert stop>=0;html=html[:start]+serialized+tail[stop:]+html[end:];p.write_text(html)
print('Packaged 8 reserved capture slots (900–907), unchanged DSP.')
