#!/usr/bin/env python3
"""Measure quiet-signal gain and clipping against the already-built NAM reference.

Run validate.py first. This audits host math, not pedal timing or its input level.
"""
import argparse
import ctypes as C
import json
import subprocess
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('build', type=Path)
a = p.parse_args()
b = a.build.resolve()
lib = C.CDLL(str(b / 'kernel.so'))
ptr = C.POINTER(C.c_float)
lib.nam_state_bytes.restype = C.c_uint
lib.nam_reset.argtypes = [C.c_void_p]
lib.nam_process.argtypes = [C.c_void_p, ptr, ptr, C.c_uint]
report = {'note': '220 Hz at model rate; Output 25 = 0.5. No hardware timing claim.',
          'levels': {}}
rate = json.loads((b / 'geometry.json').read_text())['sample_rate']
for amplitude in [0, .00001, .0001, .001, .01, .1, .5, 1]:
    x = (amplitude * np.sin(np.arange(rate * 2) * 2 * np.pi * 220 / rate)).astype(np.float32)
    y = np.zeros_like(x)
    state = C.create_string_buffer(lib.nam_state_bytes())
    lib.nam_reset(state)
    lib.nam_process(state, x.ctypes.data_as(ptr), y.ctypes.data_as(ptr), len(x))
    x.tofile(b / 'audit-input.f32')
    subprocess.run([str(b / 'reference'), str(b / 'lite.nam'),
                    str(b / 'audit-input.f32'), str(b / 'audit-reference.f32')],
                   check=True, capture_output=True)
    ref = np.fromfile(b / 'audit-reference.f32', np.float32)
    assert ref.shape == y.shape and np.isfinite(y).all()
    error = float(np.max(np.abs(ref - y)))
    assert error < 2e-5, (amplitude, error)
    tail = ref[rate:]
    report['levels'][str(amplitude)] = {
        'reference_error': error, 'peak': float(np.max(np.abs(tail))),
        'dc': float(np.mean(tail)), 'ac_rms': float(np.std(tail)),
        'output_limiter_fraction': float(np.mean(np.abs(tail * .5) > 1)),
    }
(b / 'level-audit.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
