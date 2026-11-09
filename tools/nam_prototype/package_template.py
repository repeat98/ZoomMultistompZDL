#!/usr/bin/env python3
"""Package the verified 0.12 engine without any capture coefficients."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'build'))
from zdl import Zdl
from linker import LinkerConfig, link, params_from_manifest
from capture_art import picture
from verify_capture_art import verify_audio
from gen_init_materialize import _read_elf_sections
source=ROOT/'build/probes/namlite/smokey-0.12/NAMLite.ZDL'
data=bytearray(source.read_bytes())
assert hashlib.sha256(data).hexdigest()=='06677004a5ea0a22114c6ba8ac4b0a9e09b38e3f966452f0721d3e978ab2e7ac'
old=Zdl.load(source);sections=_read_elf_sections(old.elf);c=sections['.const']
weights=old.elf[c['offset']+0x2c0:c['offset']+0x2c0+1871*4]
m=json.loads((ROOT/'src/hardware_probes/namlite/manifest.json').read_text())
output=ROOT/'build/capture-art/NAMLite.ZDL';output.parent.mkdir(exist_ok=True)
link(LinkerConfig(effect_name='NAMLite',audio_func_name=m['audio_func_name'],gid=8,fxid=498,params=params_from_manifest(m['params']),obj_path=source.with_name('namlite.obj'),output_path=output,fxid_version=b'0.12',screen_image=picture('NAM'),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(output.parent/'unused')))
z=Zdl.load(output);verify_audio(old,z,5344)
data=bytearray(output.read_bytes());start=data.index(weights)
assert data.count(weights)==1
data[start:start+1871*4]=bytes(1871*4)
out=ROOT/'tools/nam_template';out.mkdir(exist_ok=True)
(out/'engine.bin').write_bytes(data)
(out/'manifest.json').write_text(json.dumps(dict(format=1,engine='NAMLite block engine from 0.12',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),weights_offset=start,weights_count=1871,version_offset=68,output_version='0.13',sample_rate=44100),indent=2)+'\n')
print('Packaged capture-free browser template')
