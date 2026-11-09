import ctypes as C,json
from pathlib import Path
import numpy as np
OUT=Path(__file__).resolve().parents[3]/'build/probes/slo-ir'
lib=C.CDLL(str(OUT/'host.so'));lib.Fx_REV_SloIR.argtypes=[C.POINTER(C.c_size_t)];lib.slo_bytes.restype=C.c_uint;STATE_BYTES=lib.slo_bytes()
class Header(C.Structure):
 _fields_=[(k,C.c_uint) for k in ['magic','clear','ready','pad']]+[(k,C.c_float) for k in ['mix','level','tone','lp']]
class Instance:
    def __init__(self,available=None):
        if available is None:available=STATE_BYTES
        self.storage=(C.c_uint64*((max(available,STATE_BYTES)+7)//8+16))()
        C.memset(C.addressof(self.storage),0xa5,C.sizeof(self.storage))
        self.base=C.addressof(self.storage)+16
        self.available=available
        self.desc=(C.c_size_t*2)(self.base,self.base+available)
        self.params=(C.c_float*10)(1,0,0,0,0,0,.5,1)
        self.fx=(C.c_float*16)();self.out=(C.c_float*16)(*([.125]*16))
        self.src=C.c_uint(0x12345678);self.dst=C.c_uint(0)
        self.dstptr=C.pointer(self.dst)
        self.ctx=(C.c_size_t*13)()
        for i,v in [(1,self.params),(3,self.desc),(5,self.fx),(6,self.out),(11,self.dstptr),(12,self.src)]:self.ctx[i]=C.addressof(v)
        self.h=Header.from_address(self.base)
    def block(self,signal):
        self.fx[:]=signal
        lib.Fx_REV_SloIR(self.ctx)
        assert self.dst.value==self.src.value
        assert list(self.out)==[.125]*16
        assert C.string_at(C.addressof(self.storage),16)==b'\xa5'*16
        assert C.string_at(self.base+self.available,32)==b'\xa5'*32
        return np.array(self.fx[:],np.float32)

x=np.linspace(-.1,.1,16,dtype=np.float32)
short=Instance(32);assert np.array_equal(short.block(x),x)
a=Instance();b=Instance();shifted=Instance(STATE_BYTES+8);shifted.desc[0]+=4;shifted.h=Header.from_address(shifted.base+8)
for _ in range(250):
 for obj in [a,b,shifted]:assert np.array_equal(obj.block(x),x)
assert a.h.ready and b.h.ready and shifted.h.ready
for obj in [a,b]:obj.params[5]=1
wet_peak=0
for block in range(7000):
 t=np.arange(8)+block*8;mono=(.1*np.sin(t*2*np.pi*330/44100)).astype(np.float32)
 y=a.block(np.concatenate([mono,mono]));z=b.block(np.concatenate([mono,mono]))
 assert np.array_equal(y,z) and np.isfinite(y).all() and abs(y).max()<=1
 if block>2000:wet_peak=max(wet_peak,float(abs(y).max()))
assert wet_peak>1e-5
# Bypass is exact dry and retires old tail before reenable.
a.params[0]=0;assert np.array_equal(a.block(x),x) and a.h.magic==0
a.params[0]=1;assert np.array_equal(a.block(x),x) and not a.h.ready
# Wet output can be muted without changing dry level.
b.params[6]=0
for _ in range(2000):y=b.block(x)
assert abs(y).max()<1e-5
b.params[5]=0
for _ in range(2000):y=b.block(x)
assert np.max(abs(y-x))<2e-6
report=dict(passed=True,state_bytes=STATE_BYTES,wet_peak=wet_peak,checks=['guarded and 4-aligned arenas','undersized arena dry fallback','independent instances','bounded initialization','bypass clears tail','mix dry','level mute','finite output','context shuttle'])
(OUT/'wrapper-validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
