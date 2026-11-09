#!/usr/bin/env python3
"""Validate the NAMLite tone stack (Bass/Mid/Treb) on the host.

1. The float C filter (src/hardware_probes/namlite/nam_tone_stack.h + the
   generated table) against the double-precision reference in tone_stack.py:
   measured magnitude response at 12 frequencies x 7 knob settings x 3 bands,
   within 0.05 dB.
2. Knob 50 is an exact identity -- random input comes out bit for bit.
3. The real pedal wrapper (namlite.c, exact interleaved rings, the NAMFull2
   configuration) built with and without the tone stack: with all three knobs
   at 50 the two must produce BIT-IDENTICAL output, so adding the EQ cannot
   change the sound of anyone who leaves it flat. With the EQ engaged the
   output must differ and stay finite.

    python3 tools/nam_prototype/validate_tone_stack.py <model.nam>
"""
import ctypes as C, math, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE)]
import tone_stack
from generate_block import generate_block
import exact_rings

NAMLITE = ROOT / 'src/hardware_probes/namlite'
UNIT = r'''
#include "nam_tone_stack.h"
void run(unsigned band, float norm, const float *x, float *y, unsigned n){
    const float *c = nam_tone_row(band, norm); float z[2] = {0, 0}; unsigned i;
    for (i = 0; i < n; i++) y[i] = nam_biquad(c, z, x[i]);
}
'''


def cc(src, out, incs, defs=()):
    subprocess.run(['cc', '-O2', '-ffp-contract=off', '-shared', '-fPIC', '-w', *[f'-I{i}' for i in incs],
                    *[f'-D{d}' for d in defs], str(src), '-o', str(out)], check=True)
    return C.CDLL(str(out))


def main():
    model = Path(sys.argv[1]).resolve()
    P = C.POINTER(C.c_float)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        tone_stack.write_table(td)
        (td / 'unit.c').write_text(UNIT)
        u = cc(td / 'unit.c', td / 'unit.so', [td, NAMLITE])
        u.run.argtypes = [C.c_uint, C.c_float, P, P, C.c_uint]

        # 1. response vs double reference
        worst = 0.0
        n = 1 << 15
        imp = np.zeros(n, np.float32); imp[0] = 1
        for band in range(3):
            for knob in (0, 10, 30, 50, 70, 90, 100):
                y = np.zeros(n, np.float32)
                u.run(band, knob / 100, imp.ctypes.data_as(P), y.ctypes.data_as(P), n)
                H = np.fft.rfft(y.astype(np.float64)); f = np.fft.rfftfreq(n, 1 / tone_stack.FS)
                ref = tone_stack.design(tone_stack.BANDS[band], knob)
                for fr in (30, 60, 100, 150, 300, 425, 700, 1000, 1800, 3000, 6000, 12000):
                    got = 20 * math.log10(abs(H[np.argmin(abs(f - fr))]))
                    worst = max(worst, abs(got - tone_stack.response_db(ref, f[np.argmin(abs(f - fr))])))
        print(f'1. float filter vs double reference: worst error {worst:.4f} dB over 252 points')
        assert worst < 0.05

        # 2. knob 50 is an exact identity
        x = np.random.default_rng(3).uniform(-2, 2, 20000).astype(np.float32)
        for band in range(3):
            y = np.zeros_like(x); u.run(band, 0.5, x.ctypes.data_as(P), y.ctypes.data_as(P), len(x))
            assert np.array_equal(x, y), f'band {band} at knob 50 is not an exact identity'
        print('2. knob 50: all three bands are a bit-exact identity')

        # 3. real wrapper, NAMFull2 configuration, with and without the tone stack
        kdir = td / 'kernel'
        generate_block(model, kdir); exact_rings.apply(kdir, interleave=True, regacc=True); tone_stack.write_table(kdir)
        plain = cc(NAMLITE / 'namlite.c', td / 'plain.so', [kdir, ROOT / 'src/airwindows/common'])
        eq = cc(NAMLITE / 'namlite.c', td / 'eq.so', [kdir, ROOT / 'src/airwindows/common'], ['NAM_TONE_STACK'])
        gate = cc(NAMLITE / 'namlite.c', td / 'gate.so', [kdir, ROOT / 'src/airwindows/common'],
                  ['NAM_TONE_STACK', 'NAM_GATE'])

        def run(lib, knobs, sig):
            lib.Fx_FLT_NAMLite.argtypes = [C.POINTER(C.c_size_t)]
            mem = (C.c_uint8 * (4 << 20))(); b = C.addressof(mem)
            d = (C.c_size_t * 2)(b, b + (4 << 20))
            p = (C.c_float * 14)(1, 0, 0, 0, 0, *knobs, *([0.5] * (9 - len(knobs))))
            fx = (C.c_float * 16)(); src = C.c_uint(1); dst = C.c_uint(); dp = C.c_size_t(C.addressof(dst))
            ctx = (C.c_size_t * 13)()
            for k, v in [(1, p), (3, d), (5, fx), (11, dp), (12, src)]: ctx[k] = C.addressof(v)
            out = np.zeros(len(sig), np.float32)
            for i in range(0, len(sig) - 8, 8):
                fx[:8] = list(sig[i:i + 8]); fx[8:] = list(sig[i:i + 8]); lib.Fx_FLT_NAMLite(ctx); out[i:i + 8] = fx[:8]
            return out

        sr = 44100; t = np.arange(sr * 3) / sr
        sig = (0.3 * np.sin(2 * np.pi * 110 * t) * np.exp(-(t % 1.5) * 2)).astype(np.float32)
        base = run(plain, [.44, .27, 1.0], sig)
        flat = run(eq, [.44, .27, 1.0, .5, .5, .5], sig)
        d = float(np.abs(base - flat).max())
        print(f'3. wrapper, EQ flat vs no EQ: max|diff| = {d:.3e}')
        assert d == 0.0, 'flat tone stack changed the output'
        for knobs in ([.44, .27, 1.0, .5, .5, .5], [.44, .27, 1.0, .9, .2, .7]):
            g = run(gate, knobs + [0.0], sig)
            assert np.array_equal(g, run(eq, knobs, sig)), f'Gate 0 changed the output at {knobs}'
        print('4. Gate 0: bit-identical to the engine without the gate (EQ flat and 90/20/70)')
        # Gate 50 (-65 dB): -76 dB hiss alone must be muted to silence after the
        # release; while a note plays the output must equal the ungated one.
        hiss = (np.random.default_rng(5).standard_normal(len(sig)) * 10 ** (-76 / 20)).astype(np.float32)
        quiet = run(gate, [.44, .27, 1.0, .5, .5, .5, .5], hiss)
        tail_db = 20 * np.log10(np.sqrt(np.mean(quiet[2 * sr:].astype(np.float64) ** 2)) + 1e-30)
        noisy = run(eq, [.44, .27, 1.0, .5, .5, .5], hiss)
        open_db = 20 * np.log10(np.sqrt(np.mean(noisy[2 * sr:].astype(np.float64) ** 2)))
        print(f'   Gate 50, hiss only: {open_db:.1f} dBFS ungated -> {tail_db:.1f} dBFS gated')
        assert tail_db < open_db - 60
        loud = sig + hiss
        gl, ul = run(gate, [.44, .27, 1.0, .5, .5, .5, .5], loud), run(eq, [.44, .27, 1.0, .5, .5, .5], loud)
        playing = slice(int(0.3 * sr), int(1.2 * sr))      # well inside the first note
        assert np.array_equal(gl[playing], ul[playing]), 'gate changed a note while it was open'
        print('   Gate 50, while a note plays: bit-identical to ungated')
        bright = run(eq, [.44, .27, 1.0, .5, .5, .9], sig)
        s = slice(sr, None)
        assert np.all(np.isfinite(bright)) and float(np.abs(bright[s] - base[s]).max()) > 1e-3
        # Hann window: without one, the few HF bins of a cab-simulated amp are
        # swamped by leakage from the strong low notes, and a correct shelf
        # measures as ~0 dB. (It did, on the first run of this test.)
        win = np.hanning(1 << 16)
        spec = lambda v: np.abs(np.fft.rfft(v[s][:1 << 16] * win)); f = np.fft.rfftfreq(1 << 16, 1 / sr)
        hi = (f > 4000) & (f < 10000)
        lift = 20 * np.log10(spec(bright)[hi].mean() / spec(base)[hi].mean())
        print(f'   Treb 90: 4-10 kHz lifted {lift:+.1f} dB (design: +8 dB shelf above ~1.8 kHz, before the output clip)')
        assert abs(lift - 8.0) < 1.0, f'treble shelf through the wrapper measured {lift:+.1f} dB, design +8'
        s2 = slice(sr, None)
        r = spec(bright) / np.maximum(spec(base), 1e-12)
        print(f"   peak base {float(np.abs(base[s2]).max()):.3f}, bright {float(np.abs(bright[s2]).max()):.3f}, "
              f"samples at the +-1 clip: {int((np.abs(bright[s2]) >= 0.9999).sum())}")
        for lo, hi2 in ((200, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)):
            m = (f >= lo) & (f < hi2)
            want = tone_stack.response_db(tone_stack.design('treble', 90), (lo * hi2) ** 0.5)
            print(f"   median gain {lo:>5}-{hi2:<5} Hz: {20*np.log10(np.median(r[m])):+.1f} dB  (design {want:+.1f})")
        print("PASS")


if __name__ == '__main__':
    main()
