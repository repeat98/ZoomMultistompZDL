#!/usr/bin/env python3
"""Exercise the same Tonic C on host; not a TI timing or pedal fidelity test."""
import ctypes as C
import hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OUT=ROOT/'build/tonic-validation';OUT.mkdir(parents=True,exist_ok=True)
(OUT/'host.c').write_text('#include "'+str(HERE/'tonic.c')+'"\n'+r'''
unsigned tonic_state_bytes(void){return sizeof(TonicState);}
void tonic_render(uintptr_t *ctx,const float *input,float *output,unsigned n){
 float block[16];ctx[5]=(uintptr_t)block;
 for(unsigned j=0;j<n;j+=8){
  for(unsigned i=0;i<8;i++){block[i]=input[2*(j+i)];block[i+8]=input[2*(j+i)+1];}
  Fx_DLY_Tonic(ctx);
  for(unsigned i=0;i<8;i++){output[2*(j+i)]=block[i];output[2*(j+i)+1]=block[i+8];}
 }
}
''')
subprocess.run(['cc','-O2','-ffp-contract=off','-Wno-unknown-pragmas','-shared','-fPIC',str(OUT/'host.c'),'-o',str(OUT/'host.so')],check=True)
lib=C.CDLL(str(OUT/'host.so'));lib.tonic_state_bytes.restype=C.c_uint
PTR=C.POINTER(C.c_float);lib.tonic_render.argtypes=[C.POINTER(C.c_size_t),PTR,PTR,C.c_uint]
class Instance:
 def __init__(self,knobs,short=False):
  self.size=lib.tonic_state_bytes();self.arena=(C.c_uint64*((self.size+7)//8+8))()
  C.memset(C.addressof(self.arena),0xa5,C.sizeof(self.arena));self.base=C.addressof(self.arena)+16
  self.params=(C.c_float*11)(1,0,0,0,0,*[k*.01 for k in knobs])
  self.desc=(C.c_size_t*2)(self.base,self.base+(16 if short else self.size))
  self.src=C.c_uint(0x12345678);self.dst=C.c_uint(0);self.dstptr=C.pointer(self.dst)
  self.ctx=(C.c_size_t*13)()
  for i,v in [(1,self.params),(3,self.desc),(11,self.dstptr),(12,self.src)]:self.ctx[i]=C.addressof(v)
 def run(self,x):
  x=np.ascontiguousarray(x,np.float32);assert len(x)%8==0;y=np.zeros_like(x)
  lib.tonic_render(self.ctx,x.ctypes.data_as(PTR),y.ctypes.data_as(PTR),len(x))
  assert self.dst.value==self.src.value and np.isfinite(y).all()
  assert C.string_at(C.addressof(self.arena),16)==b'\xa5'*16
  assert C.string_at(self.base+self.size,16)==b'\xa5'*16
  return y
 def warm(self):self.run(np.zeros((8192,2),np.float32))

n=32768;t=np.arange(n)/44100;rng=np.random.default_rng(2026)
x=np.column_stack([.18*np.sin(2*np.pi*173*t)+.08*np.sin(2*np.pi*701*t),.15*np.sin(2*np.pi*277*t)]).astype(np.float32)
report={'source_sha256':hashlib.sha256((HERE/'tonic.c').read_bytes()).hexdigest(),'state_bytes':lib.tonic_state_bytes(),'checks':[],'modes':{}}
def passed(s):report['checks'].append(s)
a=Instance([12,80,70,50,0,0]);a.warm();assert np.array_equal(a.run(x),x);passed('Mix 0 exact stereo dry')
for mode in [12,37,62,87]:
 a=Instance([mode,0,0,0,0,100]);a.warm();assert np.array_equal(a.run(x),x)
passed('all blocks at zero exact stereo unity in every mode')
a=Instance([12,90,90,90,0,100]);a.params[0]=0;assert np.array_equal(a.run(x),x);passed('bypass exact stereo dry')
a=Instance([12,90,90,90,0,100],True);assert np.array_equal(a.run(x),x);passed('undersized arena dry')
for mode,name in [(12,'Decim'),(37,'Crush'),(62,'FM'),(87,'Ring')]:
 for amount in [1,25,60,100]:
  a=Instance([mode,amount,0,0,0,100]);a.warm();y=a.run(x)
  assert np.max(np.abs(y))<2 and np.array_equal(y[:,0],y[:,1])
  if amount==60:
   delta=float(np.sqrt(np.mean((y[:,0]-x.mean(axis=1))**2)))
   assert delta>.001,(name,delta);report['modes'][name]={'rms_change':delta,'peak':float(abs(y).max())}
passed('four mode sweeps finite; full wet mono has no separate dry channel')
f=Instance([12,70,65,55,0,100]);r=Instance([12,70,65,55,100,100]);f.warm();r.warm()
assert np.max(abs(f.run(x)-r.run(x)))>.01;passed('order changes sound')
a=Instance([37,100,0,0,0,100]);a.warm();y=a.run(np.column_stack([.2*np.sin(2*np.pi*440*t)]*2))
assert np.max(y)>.49 and np.min(y)<-.49
tail=a.run(np.zeros((65536,2),np.float32));assert np.max(abs(tail[-8192:]))<1e-6;passed('one-bit bipolar output and gate closes on silence')
a=Instance([12,0,0,60,0,100]);a.warm();assert np.max(abs(a.run(x)-x))>.01;passed('phaser works independently')
a=Instance([12,0,60,0,0,100]);a.warm();assert np.max(abs(a.run(x)-x))>.01;passed('drive works independently')
a=Instance([12,65,45,35,0,100]);b=Instance([12,65,45,35,0,100]);a.warm();b.warm();assert np.array_equal(a.run(x),b.run(x));passed('independent instances agree')
for mode in [37,62,87,12]:
 a.params[5]=mode*.01;a.params[9]=1-a.params[9];y=a.run(x);assert abs(y).max()<2
passed('mode/order transitions finite and bounded')
(OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

# Four reproducible examples from the repository guitar, same kernel/settings.
if '--samples' in sys.argv:
 import soundfile as sf
 audio,sr=sf.read(ROOT/'previews/audio/dry_guitar.wav',always_2d=True,dtype='float32');assert sr==44100
 audio=np.repeat(audio,2,axis=1) if audio.shape[1]==1 else audio[:,:2]
 audio=audio[:min(len(audio),44100*8)]*.25
 audio=np.pad(audio,((0,(-len(audio))%8),(0,0)))
 for mode,name in [(12,'decim'),(37,'crush'),(62,'fm'),(87,'ring')]:
  a=Instance([mode,60,15,20,0,70]);a.warm();y=a.run(audio)
  sf.write(OUT/(name+'.wav'),y,44100,subtype='PCM_24')
