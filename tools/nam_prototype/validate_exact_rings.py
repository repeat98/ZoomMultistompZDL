#!/usr/bin/env python3
"""Exact-size rings must be BIT-IDENTICAL to the power-of-two kernel.

Generates both kernels from the same capture, compiles each for the host with
identical flags, and runs identical input through them. Requires max |diff| = 0
-- the change is memory layout only, so any difference at all is a bug.

Stresses the parts that differ: many wraps of every ring (the largest needs
1,203 floats, so 20 s is ~730 wraps of it), partial blocks (count < 8, which
the pedal never sends but the host wrapper and reset paths can), a reset
mid-stream, and the per-layer range guard.

    python3 tools/nam_prototype/validate_exact_rings.py <model.nam>
"""
import ctypes as C, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE)]
from generate_block import generate_block
import exact_rings


def build(model, out, exact, interleave=False, regacc=False):
    generate_block(model, out)
    stats = exact_rings.apply(out, interleave, regacc) if exact else None
    so = out / 'kernel.so'
    subprocess.run(['cc', '-O2', '-ffp-contract=off', '-shared', '-fPIC',
                    str(out / 'nam_kernel.c'), '-o', str(so)], check=True)
    lib = C.CDLL(str(so))
    lib.nam_state_bytes.restype = C.c_uint
    lib.nam_reset.argtypes = [C.c_void_p]
    lib.nam_process.argtypes = [C.c_void_p, C.POINTER(C.c_float), C.POINTER(C.c_float), C.c_uint]
    return lib, stats


def run(lib, x, chunks, reset_at=None):
    st = C.create_string_buffer(lib.nam_state_bytes()); lib.nam_reset(st)
    y = np.zeros_like(x); at = 0; P = C.POINTER(C.c_float)
    for c in chunks:
        if reset_at is not None and at >= reset_at:
            lib.nam_reset(st); reset_at = None
        a = np.ascontiguousarray(x[at:at + c]); b = np.zeros(c, np.float32)
        lib.nam_process(st, a.ctypes.data_as(P), b.ctypes.data_as(P), c)
        y[at:at + c] = b; at += c
    return y, st


def main():
    model = Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p2, _ = build(model, td / 'pow2', exact=False)
        il, _ = build(model, td / 'exact-il', exact=True, interleave=True)
        ra_lib, _ = build(model, td / 'exact-il-ra', exact=True, interleave=True, regacc=True)
        ex, stats = build(model, td / 'exact', exact=True)
        print(f"state: power-of-two {p2.nam_state_bytes()} B -> exact {ex.nam_state_bytes()} B; "
              f"history {stats['history_before']*4/1024:.1f} KB -> {stats['history_after']*4/1024:.1f} KB")

        rng = np.random.default_rng(11)
        sr = 44100
        t = np.arange(sr * 20) / sr
        x = (0.3 * np.sin(2 * np.pi * 110 * t) * np.exp(-(t % 2.5))       # plucks
             + 0.05 * rng.standard_normal(len(t))).astype(np.float32)     # noise
        x[sr * 7:sr * 8] = 0                                              # silence

        cases = {
            '8-sample blocks (the pedal)': [8] * (len(x) // 8),
            'ragged blocks 1..8': None,
            '8-sample + reset at 9 s': [8] * (len(x) // 8),
        }
        rag = []; left = len(x)
        while left > 0:
            c = int(rng.integers(1, 9)); c = min(c, left); rag.append(c); left -= c
        cases['ragged blocks 1..8'] = rag

        worst = 0.0
        for name, chunks in cases.items():
            n = sum(chunks); xs = x[:n]
            ra = (sr * 9) if 'reset' in name else None
            a, _ = run(p2, xs, chunks, ra)
            b, _ = run(ex, xs, chunks, ra)
            c, _ = run(il, xs, chunks, ra)
            r2, _ = run(ra_lib, xs, chunks, ra)
            d = float(np.abs(a - b).max()); di = float(np.abs(a - c).max()); dr = float(np.abs(a - r2).max())
            worst = max(worst, d, di, dr)
            print(f"  {name:<30} planar {d:.1e}  interleaved {di:.1e}  +regacc {dr:.1e}")

        # guard: corrupt one layer's position and make sure nothing explodes
        _, st = run(ex, x[:8000], [8] * 1000)
        raw = (C.c_uint32 * (ex.nam_state_bytes() // 4)).from_buffer(st)
        # lpos sits after pos,pad,input[8],output[8],gain[8] = 2+24 words
        raw[26 + 5] = 0xFFFFFFF0
        y = np.zeros(8, np.float32); P = C.POINTER(C.c_float)
        ex.nam_process(st, np.ascontiguousarray(x[8000:8008]).ctypes.data_as(P), y.ctypes.data_as(P), 8)
        assert np.all(np.isfinite(y)), 'guard failed: non-finite output after corrupt position'
        assert raw[26 + 5] < 4096, f'guard failed: position still out of range ({raw[26+5]})'
        print("  corrupted layer position: guard reset it, output finite")

        assert worst == 0.0, f'exact rings are NOT bit-identical (max diff {worst})'
        print("PASS: exact rings are bit-identical to the power-of-two kernel")


if __name__ == '__main__':
    main()
