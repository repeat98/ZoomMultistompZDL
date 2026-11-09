import ctypes as C,json,subprocess
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/nam-timing'
subprocess.run(['cc','-O2','-ffp-contract=off','-shared','-fPIC','-DHOST_TEST','-I'+str(OUT),'-I'+str(ROOT/'src/airwindows/common'),str(HERE/'probe.c'),'-o',str(OUT/'host.so')],check=True)
l=C.CDLL(str(OUT/'host.so'));l.timing_bytes.restype=l.net_bytes.restype=C.c_uint;l.Fx_FLT_NAMTime.argtypes=[C.POINTER(C.c_size_t)];l.set_clock.argtypes=l.set_step.argtypes=[C.c_uint];l.bucket_test.argtypes=[C.c_uint,C.c_uint]
size=l.timing_bytes();net=l.net_bytes();assert net==133360
class I:
 def __init__(self):
  self.mem=(C.c_uint64*((size+128)//8))();C.memset(self.mem,165,C.sizeof(self.mem));self.base=C.addressof(self.mem)+16;self.d=(C.c_size_t*2)(self.base,self.base+size);self.p=(C.c_float*10)(1,0,0,0,0,.44,.27,1);self.fx=(C.c_float*16)();self.src=C.c_uint(12);self.dst=C.c_uint();self.dp=C.c_size_t(C.addressof(self.dst));self.ctx=(C.c_size_t*13)();self.h=(C.c_uint*11).from_address(self.base+net)
  for n,v in [(1,self.p),(3,self.d),(5,self.fx),(11,self.dp),(12,self.src)]:self.ctx[n]=C.addressof(v)
 def run(self,t):
  l.set_clock(t);self.fx[:]=[0]*16;l.Fx_FLT_NAMTime(self.ctx);assert self.dst.value==12
  assert C.string_at(self.base-16,16)==bytes([165])*16 and C.string_at(self.base+size,16)==bytes([165])*16
  return np.array(self.fx[:8])
a=I();l.set_step(42000)
for i in range(11000):a.run((0xfffffff0+i*70000)&0xffffffff)
assert a.h[1]==3 and a.h[7]==70000 and a.h[8]==42000 and a.h[6]==42000,list(a.h)
# Simulate a100% peak but60% average, and verify both audible groups.
a.h[6]=70000;a.h[9]=0;out=[]
for i in range(33075):out.extend(a.run(i*70000))
g=np.array(out).reshape(2,15,8820);counts=(np.max(abs(g),axis=2)>1e-5).sum(1);assert list(counts)==[3,5],counts
for cost,expected in [(0,2),(34999,2),(35000,3),(55999,3),(56000,4),(69999,4),(70000,5)]:assert l.bucket_test(cost,70000)==expected
assert l.bucket_test(0,0)==1
b=I();l.set_step(0)
for i in range(4200):b.run(0)
assert b.h[1]==3 and b.h[7]==0
# Bypass resets measurement; reenable restarts low-load calibration.
a.p[0]=0;a.run(0);assert a.h[0]==0;a.p[0]=1;a.run(0);assert a.h[1]==0
r=dict(passed=True,state_bytes=size,checks=['timer rollover calibration','simulated actual core duration','mean and peak category boundaries','low/high beep counts','stopped timer inconclusive result','arena guards','bypass restart'],hardware='pending');(OUT/'host-validation.json').write_text(json.dumps(r,indent=2)+'\n');print(r)
