#!/usr/bin/env python3
"""Exercise the pedal wrapper with guarded per-instance arenas on the host."""
import argparse
import ctypes as C
import json
import subprocess
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--build',type=Path,default=ROOT/'build/probes/namlite');args=parser.parse_args()
OUT=args.build.resolve()
shim=OUT/'host-wrapper.c'
shim.write_text('#include "'+str(HERE/'namlite.c')+'"\nunsigned nam_wrapper_bytes(void){return sizeof(PedalNam);}\n')
subprocess.run(['cc','-O2','-ffp-contract=off','-shared','-fPIC',
    '-Wno-unknown-pragmas', '-I'+str(OUT),
    '-I'+str(ROOT/'src/airwindows/common'),str(shim),
    '-o',str(OUT/'host.so')],check=True)
lib=C.CDLL(str(OUT/'host.so'));lib.Fx_FLT_NAMLite.argtypes=[C.POINTER(C.c_size_t)]
lib.nam_wrapper_bytes.restype=C.c_uint
STATE_BYTES=lib.nam_wrapper_bytes()
class Header(C.Structure):
    _fields_=[(k,C.c_uint) for k in ['magic','version','clear_index','ready','warm']]+[(k,C.c_float) for k in ['mix','input','output']]+[('pos',C.c_uint)]
class Instance:
    def __init__(self,available=None):
        if available is None:available=STATE_BYTES
        self.storage=(C.c_uint64*((max(available,STATE_BYTES)+7)//8+16))()
        C.memset(C.addressof(self.storage),0xa5,C.sizeof(self.storage))
        self.base=C.addressof(self.storage)+16
        self.available=available
        self.desc=(C.c_size_t*2)(self.base,self.base+available)
        self.params=(C.c_float*10)(1,0,0,0,0,.5,.25,0)
        self.fx=(C.c_float*16)();self.out=(C.c_float*16)(*([.125]*16))
        self.src=C.c_uint(0x12345678);self.dst=C.c_uint(0)
        self.dstptr=C.pointer(self.dst)
        self.ctx=(C.c_size_t*13)()
        for i,v in [(1,self.params),(3,self.desc),(5,self.fx),(6,self.out),(11,self.dstptr),(12,self.src)]:self.ctx[i]=C.addressof(v)
        self.h=Header.from_address(self.base)
    def block(self,signal):
        self.fx[:]=signal
        lib.Fx_FLT_NAMLite(self.ctx)
        assert self.dst.value==self.src.value
        assert list(self.out)==[.125]*16
        assert C.string_at(C.addressof(self.storage),16)==b'\xa5'*16
        assert C.string_at(self.base+self.available,32)==b'\xa5'*32
        return np.array(self.fx[:],np.float32)
a=Instance();b=Instance();x=np.linspace(-.1,.1,16,dtype=np.float32)
# Invalid/short arena must leave audio untouched.
short=Instance(32);assert np.array_equal(short.block(x),x)
# A 4-aligned host allocation must be aligned internally, not silently rejected.
shifted=Instance(STATE_BYTES+8)
shifted.desc[0]+=4
shifted.h=Header.from_address(shifted.base+8)
for _ in range(80):assert np.array_equal(shifted.block(x),x)
assert shifted.h.ready and shifted.h.pos==0
# Default zero Mix remains exact dry even after incremental initialization.
for _ in range(80):assert np.array_equal(a.block(x),x)
assert a.h.ready and a.h.pos==0
# Bypassed with a wet knob must remain dry and not run the network.
a.params[0]=0;a.params[7]=1
assert np.array_equal(a.block(x),x) and a.h.pos==0
a.params[0]=1
# Two independent instances, initialized with different backing addresses.
for _ in range(80):b.block(x)
b.params[7]=1
peak=0.;delta=0.
for block in range(1800):
    t=np.arange(8)+8*block
    mono=(.1*np.sin(t*2*np.pi*440/44100)).astype(np.float32)
    stereo=np.concatenate([mono,mono])
    y=a.block(stereo);z=b.block(stereo)
    assert np.array_equal(y,z), 'Instance interference'
    assert np.isfinite(y).all() and abs(y).max()<=1
    peak=max(peak,float(abs(y).max()))
    if block>1400:delta=max(delta,float(abs(y-stereo).max()))
assert a.h.warm==8192 and delta>.01
# Verify actual smoothed drive at the low-end settings used for noise tests.
for knob, gain in [(0,0),(1,.0004),(5,.01),(10,.04),(25,.25),(50,1),(100,2)]:
    a.params[5]=knob/100
    for _ in range(1500):a.block(x)
    # Float32 smoothing settles within a few ULPs / 0.002 of its target.
    assert abs(a.h.input-gain)<4e-5,(knob,a.h.input,gain)
# Output=0 mutes the wet signal after smoothing settles.
a.params[6]=0
for _ in range(1500):y=a.block(x)
assert abs(y).max()<1e-5
# Mix=0 returns to exact dry and parks the network after its fade.
a.params[7]=0
for _ in range(1000):y=a.block(x)
assert np.array_equal(y,x)
pos=a.h.pos
for _ in range(20):assert np.array_equal(a.block(x),x)
assert a.h.pos==pos
report=dict(passed=True,arena_bytes=STATE_BYTES,wet_peak=peak,max_wet_dry_difference=delta,
    checks=['guarded arenas','4-aligned arena','undersized arena','magic shuttle','in-place audio only',
    'default dry','bypass','independent instances','warmup','finite bounded output',
    'audible neural response','low-end input attenuation','output mute','mix zero parks CPU'])
(OUT/'host-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
