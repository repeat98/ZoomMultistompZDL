#!/usr/bin/env python3
"""Screen lossless/full-rate A2 Lite scheduling variants; never publish to dist.

Private capture weights remain in the chosen build directory. These are
experiments, not converter engines. Test host and actual target output before
considering a hardware trial. Version0.16 is experimental and unreleased.
"""
from pathlib import Path
import argparse,sys,subprocess,json
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'tools/nam_prototype'),str(ROOT/'build')]
from generate_block import generate_block
from linker import *
from capture_art import picture
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('model',type=Path)
p.add_argument('variant',choices=['local','samplelocal','samplefixed','samplesplit','flat','fused','pairtap','pairtap2','reassoc'])
p.add_argument('--out',type=Path)
p.add_argument('--short-name',default='trial',help='ASCII capture name, 1–8 letters/digits/hyphen/underscore')
args=p.parse_args();model=args.model
import re
if not re.fullmatch(r'[A-Za-z0-9_-]{1,8}',args.short_name):p.error('short name must contain 1–8 ASCII letters/digits/hyphens/underscores')
variant=args.variant;out=(args.out or ROOT/'build/probes/namlite'/('opt-'+variant)).resolve();generate_block(model,out)
h=(out/'nam_kernel_pedal.h').read_text()
if 'local' in variant:
 for field,var in [('v','v'),('sum','sum'),('z','zbuf')]:h=h.replace(f'float * restrict {var}=s->{field};',f'float {var}[30];')
if 'sample' in variant:
 a=h.index('        for(t=0;t<k;t++)');b=h.index('        for(i=0;i<count;i++)',a+30) # replace via end marker
 b=h.index('        for(i=0;i<count;i++) {\n            float x=',a)
 h=h[:a]+'''        for(i=0;i<count;i++) {
            float z0=b[0],z1=b[1],z2=b[2];
            const float *cw=w;
            for(t=0;t<k;t++) {
                q=(pos+i-(k-1-t)*d)&(n-1);
                float a=h[q],c=h[stride+q],e=h[2*stride+q];
                z0+=cw[0]*a;z0+=cw[1]*c;z0+=cw[2]*e;
                z1+=cw[3]*a;z1+=cw[4]*c;z1+=cw[5]*e;
                z2+=cw[6]*a;z2+=cw[7]*c;z2+=cw[8]*e;
                cw+=9;
            }
            zbuf[i]=z0;zbuf[10+i]=z1;zbuf[20+i]=z2;
        }
'''+h[b:]
if 'split' in variant:
 a=h.index('        for(i=0;i<count;i++) {\n            float z0=b[0]');b=h.index('        for(i=0;i<count;i++) {\n            float x=',a)
 body=h[a:b]
 fast=body.replace('for(t=0;t<k;t++)','for(t=0;t<6;t++)').replace('(k-1-t)','(5-t)').replace('            for(t=0;', '            #pragma UNROLL(6)\n            for(t=0;')
 h=h[:a]+'        if(k==6) {\n'+fast+'        } else {\n'+body+'        }\n'+h[b:]
if 'fixed' in variant:
 a=h.index('            for(t=0;t<k;t++)');b=h.index('            zbuf[i]=z0;',a)
 body=h[a:b]
 fast=body.replace('for(t=0;t<k;t++)','for(t=0;t<6;t++)').replace('(k-1-t)','(5-t)')
 fast='            #pragma UNROLL(6)\n'+fast
 h=h[:a]+'            if(k==6) {\n'+fast+'            } else {\n'+body+'            }\n'+h[b:]
if 'flat' in variant:
 a=h.index('        for(t=0;t<k;t++)');b=h.index('        for(i=0;i<count;i++) {\n            float x=',a)
 h=h[:a]+"""        for(unsigned it=0;it<k*count;it++) {
            i=it%count;t=it/count;
            const float *cw=w+9*t;
            q=(pos+i-(k-1-t)*d)&(n-1);
            float a=h[q],c=h[stride+q],e=h[2*stride+q];
            float z0=zbuf[i],z1=zbuf[10+i],z2=zbuf[20+i];
            z0+=cw[0]*a;z0+=cw[1]*c;z0+=cw[2]*e;
            z1+=cw[3]*a;z1+=cw[4]*c;z1+=cw[5]*e;
            z2+=cw[6]*a;z2+=cw[7]*c;z2+=cw[8]*e;
            zbuf[i]=z0;zbuf[10+i]=z1;zbuf[20+i]=z2;
        }
"""+h[b:]
if 'fused' in variant:
 h=h.replace('            zbuf[i]=b[0];zbuf[10+i]=b[1];zbuf[20+i]=b[2];','')
 a=h.index('        for(t=0;t<k;t++)');b=h.index('        w=b+18;',a)
 conv=h[a:h.index('        for(i=0;i<count;i++) {\n            float x=',a)]
 body=conv[conv.index('            for(i=0;i<count;i++) {'):conv.index('            w+=9;')]
 first=body.replace('float z0=zbuf[i],z1=zbuf[10+i],z2=zbuf[20+i];','float z0=b[0],z1=b[1],z2=b[2];').replace('(k-1-t)*d','(k-1)*d')
 coeff=conv[conv.index('            float w0='):conv.index('            for(i=0;')]
 final=h[h.index('        for(i=0;i<count;i++) {\n            float x=',a):b]
 final=final[final.index('            float x='):final.rindex('        }')]
 final=final.replace('float z0=zbuf[i]+b[3]*x,z1=zbuf[10+i]+b[4]*x,z2=zbuf[20+i]+b[5]*x;', 'z0+=b[3]*x;z1+=b[4]*x;z2+=b[5]*x;')
 last=body.replace('(k-1-t)*d','0').replace('            zbuf[i]=z0;zbuf[10+i]=z1;zbuf[20+i]=z2;',final)
 middle=conv.replace('t=0;t<k;t++','t=1;t<k-1;t++')
 h=h[:a]+'        {\n'+coeff+first+'        }\n        w+=9;\n'+middle+'        {\n'+coeff+last+'        }\n'+h[b:]

if 'pairtap' in variant:
 a=h.index('        for(t=0;t<k;t++)');b=h.index('        for(i=0;i<count;i++) {\n            float x=',a)
 orig=h[a:b]
 pair=orig.replace('t=0;t<k;t++','t=0;t+1<k;t+=2').replace('w+=9;', 'w+=18;')
 pair=pair.replace('            for(i=0;i<count;i++) {', '            float u0=w[9],u1=w[10],u2=w[11],u3=w[12],u4=w[13],u5=w[14],u6=w[15],u7=w[16],u8=w[17];\n            for(i=0;i<count;i++) {')
 pair=pair.replace('                zbuf[i]=z0;', '''                q=(pos+i-(k-2-t)*d)&(n-1);
                a=h[q];c=h[stride+q];e=h[2*stride+q];
                z0+=u0*a;z0+=u1*c;z0+=u2*e;
                z1+=u3*a;z1+=u4*c;z1+=u5*e;
                z2+=u6*a;z2+=u7*c;z2+=u8*e;
                zbuf[i]=z0;''')
 tail=orig.replace('for(t=0;t<k;t++)','if(t<k)')
 h=h[:a]+pair+tail+h[b:]
if variant == 'pairtap2':
 h=h.replace('            for(i=0;i<count;i++) {', '            #pragma UNROLL(2)\n            for(i=0;i<count;i++) {')
(out/'nam_kernel_pedal.h').write_text(h)
s=(out/'nam_kernel.c').read_text();suffix=s[s.index('unsigned nam_state_bytes'):];(out/'nam_kernel.c').write_text(h+suffix)
ti=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS');obj=out/'namlite.obj'
subprocess.run([str(ti/'bin/cl6x'),'--c99','-O2','-mv6740','--abi=eabi','--mem_model:data=far','--fp_mode=strict',('--fp_reassoc=on' if 'reassoc' in variant else '--fp_reassoc=off'),f'--include_path={ti}/include',f'--include_path={ROOT}/src/airwindows/common',f'--include_path={out}','--keep_asm',f'--asm_directory={out}','-c',str(ROOT/'src/hardware_probes/namlite/namlite.c'),f'--output_file={obj}'],check=True,timeout=900)
o=ObjFile(obj)
assert not any(v['name'] and not v['shndx'] for v in o.symbols)
for sec in o.sections:
 if sec['name'] in ('.text','.bss','.far','.fardata') or sec['name'].startswith('.switch'):assert not sec['size']
m=json.loads((ROOT/'src/hardware_probes/namlite/manifest.json').read_text())
link(LinkerConfig(effect_name='NAMSlot1',audio_func_name=m['audio_func_name'],gid=8,fxid=900,params=params_from_manifest(m['params']),obj_path=obj,output_path=out/'NAMLite.ZDL',fxid_version=b'0.16',screen_image=picture('NAM'),materialize_init=True,use_object_edit_handlers=False,synthesize_linesel_edit_handlers=True,synth_edit_start_index=2,knob3_blob_path=str(out/'unused')))

# Name-only metadata update; coefficient/audio bytes are untouched.
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
dest=out/'NAMLite.ZDL';z=Zdl.load(dest);c=_read_elf_sections(z.elf)['.const']
base=20+z.header_size+c['offset'];data=bytearray(dest.read_bytes())
name=data.index(b'OnOff\0',base)+48
assert data[name:name+8]==b'NAMSlot1'
data[name:name+12]=('NAM-'+args.short_name).encode().ljust(12,b'\0')
dest.write_bytes(data)
