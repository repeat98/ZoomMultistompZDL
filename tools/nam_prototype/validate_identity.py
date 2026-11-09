#!/usr/bin/env python3
"""Assert that the diagnostic network reproduces input, not just NAM Core."""
import argparse
import ctypes as C
import json
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('build',type=Path)
a=p.parse_args();b=a.build.resolve()
lib=C.CDLL(str(b/'kernel.so'));ptr=C.POINTER(C.c_float)
lib.nam_state_bytes.restype=C.c_uint
lib.nam_reset.argtypes=[C.c_void_p]
lib.nam_process.argtypes=[C.c_void_p,ptr,ptr,C.c_uint]
rng=np.random.default_rng(2026)
signals={'silence':np.zeros(32768,np.float32),
         'random':rng.uniform(-1,1,32768).astype(np.float32),
         'quiet':rng.uniform(-1e-5,1e-5,32768).astype(np.float32),
         'alternating':np.tile(np.array([-1,1],np.float32),16384)}
report={}
for name,x in signals.items():
    s=C.create_string_buffer(lib.nam_state_bytes());lib.nam_reset(s)
    y=np.zeros_like(x)
    for start in range(0,len(x),8):
        lib.nam_process(s,x[start:].ctypes.data_as(ptr),y[start:].ctypes.data_as(ptr),8)
    error=float(np.max(np.abs(y-x)))
    assert np.isfinite(y).all() and error<2e-6,(name,error)
    if name=='silence':assert np.count_nonzero(y)==0
    report[name]={'max_identity_error':error}
(b/'identity-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
