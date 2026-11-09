import ctypes as C,json,subprocess
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/nam-memory'
subprocess.run(['cc','-O2','-shared','-fPIC','-DHOST_TEST',str(HERE/'probe.c'),'-o',str(OUT/'host.so')],check=True)
l=C.CDLL(str(OUT/'host.so'));l.probe_bytes.restype=C.c_uint;l.Fx_FLT_NAMMem.argtypes=[C.POINTER(C.c_size_t)];size=l.probe_bytes();assert size==133360
class I:
 def __init__(self,short=False,shift=0):
  self.mem=(C.c_uint64*((size+128)//8))();C.memset(self.mem,165,C.sizeof(self.mem));self.base=C.addressof(self.mem)+16+shift;self.end=self.base+(16 if short else size+8);self.d=(C.c_size_t*2)(self.base,self.end);self.p=(C.c_float*8)(1,0,0,0,0,.01);self.fx=(C.c_float*16)();self.src=C.c_uint(123);self.dst=C.c_uint();self.dp=C.c_size_t(C.addressof(self.dst));self.ctx=(C.c_size_t*13)()
  for n,v in [(1,self.p),(3,self.d),(5,self.fx),(11,self.dp),(12,self.src)]:self.ctx[n]=C.addressof(v)
  self.h=(C.c_uint*8).from_address((self.base+7)&~7)
 def run(self):
  self.fx[:]=[0]*16;l.Fx_FLT_NAMMem(self.ctx);assert self.dst.value==123
  assert C.string_at(C.addressof(self.mem),16)==bytes([165])*16 and C.string_at(self.end,16)==bytes([165])*16
  assert max(abs(v) for v in self.fx)<=.025001
  return list(self.fx)
a=I();b=I(shift=4)
for i in range(12000):assert a.run()==b.run()
assert a.h[4]==2 and a.h[3]==0 and a.h[2]>8
# Inject a retained-memory error ahead of the scanning cursor.
at=a.h[1];cell=C.c_uint.from_address(a.base+32+at*4);cell.value^=1;a.run();assert a.h[3]==1
for i in range(22000):a.run()
assert a.h[3]==1
# Four pulses during a full stable two-second cycle; healthy instance has two.
for instance,count in [(a,4),(b,2)]:
 instance.h[6]=0;v=[]
 for i in range(11025):v.extend(instance.run()[:8])
 energy=np.array(v).reshape(10,8820);assert sum(np.max(abs(energy),axis=1)>1e-5)==count
# Reset explicitly through Test, then verify clean memory again.
a.p[5]=0;a.run();assert a.h[0]==0;a.p[5]=.01
for i in range(2200):a.run()
assert a.h[3]==0 and a.h[4]==2
small=I(short=True);small.run();assert bytes(small.mem)[16:32]==bytes([165])*16
b.p[0]=0;before=bytes(b.mem);b.run();assert bytes(b.mem)==before
r=dict(passed=True,state_bytes=size,checks=['retained pattern over multiple complete sweeps','independent and four-aligned guarded arenas','injected bit error latched','two versus four audible pulse groups','Test reset','undersized arena untouched','bypass does not alter state'],hardware='pending')
(OUT/'host-validation.json').write_text(json.dumps(r,indent=2)+'\n');print(r)
