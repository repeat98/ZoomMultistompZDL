#!/usr/bin/env python3
"""Reproducible host renders of current release C kernels (not ZDL emulation).
Requires built *_params.h headers, cc, numpy and soundfile. Never touches DSP files.
Only firmware pointer plumbing is replaced; audio/initialization code stays intact.
"""
import ctypes, hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from build_all import RELEASE_PLUGINS
OUT=ROOT/'previews/audio'
SOURCES={'tapeecho4':'guitar','totape9':'chord','galactic':'chord','taffy':'guitar','dissolve':'drums','mangle':'drums','rooms':'chord','rewire':'guitar','dustbox':'riff','stasis':'chord','gyre':'guitar'}

def render(key,build):
    folder=build.parent; source=folder/(key+'.c')
    manifest=folder/('manifest_pedal.json' if 'manifest_pedal.json' in build.read_text() else 'manifest.json')
    m=json.loads(manifest.read_text());name=m['effect_name']
    params={p['name']:p['default'] for p in m['params']}
    dry=OUT/f'dry_{SOURCES[key]}.wav'
    audio,sr=sf.read(dry,always_2d=True,dtype='float32');assert sr==44100
    audio=np.repeat(audio,2,axis=1) if audio.shape[1]==1 else audio[:,:2]
    audio=audio*.25 # fixed input attenuation for all new previews; no loudness matching
    tail=5; n=len(audio)+sr*tail;n=(n+7)//8*8
    x=np.zeros((n,2),np.float32);x[:len(audio)]=audio
    p=np.zeros(20,np.float32);p[0]=p[4]=1
    for i,v in enumerate(params.values()):p[5+i]=v*.01
    if key=='stasis':p[10]=.01;params['Capture']='Release, then Hold at 1.5 seconds'
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        code=subprocess.check_output(['cc','-include','stdlib.h','-E','-P','-Wno-unknown-pragmas',str(source)],text=True)
        pattern=r'void \w+\(unsigned int \*ctx\)\s*\{.*?\*magicDst = \*magicSrc;'
        code,count=re.subn(pattern,'void host_process(float *params,float *fxBuf,void *arena){',code,flags=re.S)
        assert count==1,(key,count)
        code,count=re.subn(r'volatile unsigned int \*desc = .*?;', 'uintptr_t descriptor[3]={(uintptr_t)arena,(uintptr_t)arena+8388608,8388608}; uintptr_t *desc=descriptor;',code)
        assert count==1,(key,'arena',count)
        code+='''\nint render(float *p,float *input,float *output,int n,int capture){
 void *arena=calloc(1,8388608);if(!arena)return 1;
 float block[16]={0};
 for(int j=0;j<8192;j++){for(int k=0;k<16;k++)block[k]=0;host_process(p,block,arena);}
 for(int i=0;i<n;i+=8){
  if(capture && i>=66150)p[10]=.02f;
  for(int k=0;k<8;k++){block[k]=input[2*(i+k)];block[k+8]=input[2*(i+k)+1];}
  host_process(p,block,arena);
  for(int k=0;k<8;k++){output[2*(i+k)]=block[k];output[2*(i+k)+1]=block[k+8];}
 }free(arena);return 0;
}
'''
        c=tmp/'kernel.c';c.write_text(code);lib=tmp/'kernel.dylib'
        subprocess.run(['cc','-O2','-fno-strict-aliasing','-shared','-fPIC','-Wno-unknown-pragmas',str(c),'-o',str(lib)],check=True)
        fn=ctypes.CDLL(str(lib)).render;ptr=np.ctypeslib.ndpointer(dtype=np.float32,flags='C_CONTIGUOUS');fn.argtypes=[ptr,ptr,ptr,ctypes.c_int,ctypes.c_int]
        y=np.zeros_like(x);assert fn(p,x,y,n,int(key=='stasis'))==0
        if 'Mix' in params:
            dry_params=p.copy();dry_params[5+list(params).index('Mix')]=0
            probe=np.zeros_like(x)
            assert fn(dry_params,x,probe,n,int(key=='stasis'))==0
            assert np.allclose(probe,x,atol=2e-6), (key,'Mix=0 must preserve input')

    assert np.isfinite(y).all() and np.max(np.abs(y))>1e-6
    peak=float(np.max(np.abs(y)));gain=min(1,.95/peak);y*=gain
    # Short fade avoids a hard cut through reverb/freeze tails.
    fade=min(sr//10,n);y[-fade:]*=np.linspace(1,0,fade)[:,None]
    dest=OUT/(name.lower()+'.wav');sf.write(dest,y,sr,subtype='PCM_24')
    return {'effect':name,'file':dest.name,'source':dry.name,'parameters':params,'input_gain':.25,'output_gain':gain,'tail_seconds':tail,'peak_before_output_gain':peak,'peak':float(np.max(np.abs(y))),'rms':float(np.sqrt(np.mean(y*y))),'source_c':str(source.relative_to(ROOT)),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'method':'current C kernel compiled for host; firmware pointers replaced; 8192 silent warm-up blocks; not a pedal recording'}

if __name__=='__main__':
    rows=[]
    for key,build in RELEASE_PLUGINS:
        if key in SOURCES:
            print(key,flush=True);rows.append(render(key,build))
    (OUT/'release_samples.json').write_text(json.dumps(rows,indent=2)+'\n')
