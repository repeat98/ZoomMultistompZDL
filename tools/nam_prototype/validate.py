#!/usr/bin/env python3
"""Compare generated C against upstream NAM Core and check block invariance."""
import argparse, ctypes, json, subprocess, time
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('build');p.add_argument('core')
p.add_argument('--reference-executable',type=Path,help='Reuse an already-built unchanged NAM Core reference')
a=p.parse_args()
b=Path(a.build).resolve();core=Path(a.core).resolve();here=Path(__file__).resolve().parent
sources=sorted(core.glob('NAM/*.cpp'))+sorted(core.glob('NAM/*/*.cpp'))
reference=a.reference_executable.resolve() if a.reference_executable else b/'reference'
if a.reference_executable:
    assert reference.is_file(),reference
else:
    subprocess.run(['c++','-std=c++20','-O2','-ffp-contract=off','-DNAM_SAMPLE_FLOAT','-DNAM_ENABLE_A2_FAST','-I'+str(core),'-I'+str(core/'Dependencies/eigen'),'-I'+str(core/'Dependencies/nlohmann'),str(here/'reference.cpp'),*map(str,sources),'-o',str(reference)],check=True)
subprocess.run(['cc','-O2','-ffp-contract=off','-shared','-fPIC',str(b/'nam_kernel.c'),'-o',str(b/'kernel.so')],check=True)
lib=ctypes.CDLL(str(b/'kernel.so'));ptr=ctypes.POINTER(ctypes.c_float)
lib.nam_state_bytes.restype=ctypes.c_uint
lib.nam_reset.argtypes=[ctypes.c_void_p]
lib.nam_process.argtypes=[ctypes.c_void_p,ptr,ptr,ctypes.c_uint]
def run(x,block):
    state=ctypes.create_string_buffer(lib.nam_state_bytes());lib.nam_reset(state)
    y=np.zeros_like(x)
    for start in range(0,len(x),block):
        n=min(block,len(x)-start)
        lib.nam_process(state,x[start:].ctypes.data_as(ptr),y[start:].ctypes.data_as(ptr),n)
    return y
n=16384;rng=np.random.default_rng(2026)
impulse=np.zeros(n,np.float32);impulse[0]=.5
signals={'silence':np.zeros(n,np.float32),'impulse':impulse,'noise':rng.uniform(-.2,.2,n).astype(np.float32),'sine':(.1*np.sin(np.arange(n)*2*np.pi*440/48000)).astype(np.float32)}
report={}
for name,x in signals.items():
    x.tofile(b/'input.f32')
    subprocess.run([str(reference),str(b/'lite.nam'),str(b/'input.f32'),str(b/'output.f32')],check=True)
    ref=np.fromfile(b/'output.f32',np.float32);y=run(x,8)
    assert len(ref)==n and np.isfinite(y).all()
    error=float(np.max(np.abs(y-ref)))
    assert error<2e-5,(name,error)
    assert np.array_equal(y,run(x,257)) and np.array_equal(y,run(x,8))
    report[name]={'max_absolute_error':error,'rms_error':float(np.sqrt(np.mean((y-ref)**2))),'block_and_reset_exact':True}
x=signals['noise'];start=time.perf_counter()
for _ in range(10):run(x,len(x))
report['host_samples_per_second']=10*n/(time.perf_counter()-start)
report['note']='Host throughput is NOT a TI DSP timing measurement.'
(b/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
