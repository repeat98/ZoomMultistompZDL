#!/usr/bin/env python3
"""Host end-to-end test of NAMProf: probe -> report audio -> decoder.

Compiles probe.c for the host with a fake cycle counter and fake cache
registers, drives it through every stage (interval calibration, warm-up,
4096 timed callbacks, report), renders the report to a WAV at 44.1 and 48 kHz,
and requires tools/decode_namprof.py to recover every word exactly. Also checks
the arena guard bytes are never touched and the magic shuttle is preserved.

Run build.py first (it prepares build/probes/nam-profile/).
"""
import ctypes as C, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'build/probes/nam-profile'
sys.path.insert(0, str(ROOT / 'tools'))
import decode_namprof as dec

so = OUT / 'host.so'
subprocess.run(['cc', '-O2', '-ffp-contract=off', '-shared', '-fPIC', '-DHOST_TEST',
                '-I' + str(OUT), '-I' + str(ROOT / 'src/airwindows/common'),
                str(HERE / 'probe.c'), '-o', str(so)], check=True)
l = C.CDLL(str(so))
l.prof_bytes.restype = l.net_bytes.restype = C.c_uint
l.Fx_FLT_NAMProf.argtypes = [C.POINTER(C.c_size_t)]
l.set_clock.argtypes = l.set_step.argtypes = [C.c_uint]
l.set_regs.argtypes = [C.c_uint] * 3

size = l.prof_bytes()
GUARD = 16
mem = (C.c_uint8 * (size + 2 * GUARD + 16))()
C.memset(mem, 0xA5, C.sizeof(mem))
base = (C.addressof(mem) + GUARD + 7) & ~7
d = (C.c_size_t * 2)(base, base + size)
p = (C.c_float * 10)(1, 0, 0, 0, 0, .44, .27, 1)
fx = (C.c_float * 16)()
src = C.c_uint(0x1234ABCD); dst = C.c_uint(); dp = C.c_size_t(C.addressof(dst))
ctx = (C.c_size_t * 13)()
for n, v in [(1, p), (3, d), (5, fx), (11, dp), (12, src)]:
    ctx[n] = C.addressof(v)

STEP = 55555
l.set_regs(0x3, 0x3, 0x1)          # the values read statically from the firmware
l.set_step(STEP)
l.set_clock(0xFFFFF000)            # force a wrap mid-measurement

rng = np.random.default_rng(1)
report = []
for cb in range(12000 + 40000):
    fx[:] = list(rng.uniform(-.3, .3, 16).astype(np.float32))
    l.Fx_FLT_NAMProf(ctx)
    assert dst.value == 0x1234ABCD, 'magic shuttle not preserved'
    if cb >= 12000:
        report.extend(fx[:8])
    assert bytes(mem[:base - C.addressof(mem)]) == b'\xa5' * (base - C.addressof(mem)), 'wrote below arena'
    assert bytes((C.c_uint8 * GUARD).from_address(base + size)) == b'\xa5' * GUARD, 'wrote past arena'

y = np.array(report, np.float32)
assert np.abs(y).max() > 0.05, 'no report audio -- probe never reached stage 3'
for sr in (44100, 48000):
    wav = OUT / f'selftest_{sr}.wav'
    yy = y if sr == 44100 else np.interp(np.arange(0, len(y), 44100 / sr), np.arange(len(y)), y)
    sf.write(wav, (yy * 0.8 + rng.normal(0, 0.002, len(yy))).astype(np.float32), sr)
    r = dec.decode(str(wav))
    # With a constant fake step: stage 0 period == STEP; every timed call == STEP.
    expect = dict(period=STEP, avg=STEP, peak=STEP, min=STEP, arena_base=d[0], arena_end=d[1],
                  arena_mar=1, l1dcfg=3, l2cfg=3, ctx=C.addressof(ctx) & 0xffffffff,
                  fx=C.addressof(fx) & 0xffffffff)
    for k, v in expect.items():
        assert r[k] == (v & 0xffffffff), f'{sr} Hz: {k} decoded 0x{r[k]:08x}, expected 0x{v & 0xffffffff:08x}'
    print(f'{sr} Hz: decoded all {len(dec.WORDS)} words exactly (period/avg/peak/min={STEP}, regs, addresses)')
print('NAMProf host end-to-end test passed')
