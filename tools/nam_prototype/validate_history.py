#!/usr/bin/env python3
"""Verify 0.09 against a known delay, independently of the NAM reference."""
import argparse
import ctypes as C
import json
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser(description=__doc__);p.add_argument('build',type=Path)
b=p.parse_args().build.resolve()
lib=C.CDLL(str(b/'kernel.so'));ptr=C.POINTER(C.c_float)
lib.nam_state_bytes.restype=C.c_uint
lib.nam_reset.argtypes=[C.c_void_p]
lib.nam_process.argtypes=[C.c_void_p,ptr,ptr,C.c_uint]
lag=json.loads((b/'binary-validation.json').read_text())['delay_samples']
n=65536;rng=np.random.default_rng(2026)
impulse=np.zeros(n,np.float32);impulse[0]=.5;impulse[8191]=-.5
signals={'silence':np.zeros(n,np.float32),'impulses':impulse,
         'random':rng.uniform(-1,1,n).astype(np.float32),
         'quiet':rng.uniform(-1e-4,1e-4,n).astype(np.float32),
         'alternating':np.tile(np.array([-1,1],np.float32),n//2)}
report={'delay_samples':lag,'signals':{}}
for name,x in signals.items():
    expected=np.zeros_like(x);expected[lag:]=x[:-lag]
    # Bias cancellation begins once the 16-tap head contains channel 2.
    # On hardware this is hidden by the existing muted 8192-sample warmup.
    expected[:15]=-2
    outputs=[]
    for block in (8,257):
        s=C.create_string_buffer(lib.nam_state_bytes());lib.nam_reset(s)
        y=np.zeros_like(x)
        for start in range(0,n,block):
            lib.nam_process(s,x[start:].ctypes.data_as(ptr),y[start:].ctypes.data_as(ptr),min(block,n-start))
        assert np.isfinite(y).all()
        outputs.append(y)
    assert np.array_equal(*outputs)
    error=float(np.max(np.abs(outputs[0]-expected)))
    assert error<2e-5,(name,error)
    report['signals'][name]={'max_delay_error':error,'block_invariant':True}
(b/'history-validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
