#!/usr/bin/env python3
"""Run NAMLite's host build and its TI build (in Ziddle) on the same input and
compare. Also writes the standard test input if it is missing.

    python3 tools/nam_prototype/host_vs_emulator.py <ZDL> <kernel_dir> <knobs> [-D...]

knobs: comma-separated 0-100 values as namcheck takes them (Input,Output,Mix,
Bass,Mid,Treb,Gate). -D flags: the defines the ZDL was built with, e.g.
-DNAM_TONE_STACK -DNAM_GATE -DNAM_FAST_IO. Ziddle lives in ~/ziddle (see
docs/EMULATOR-TESTING.md); never keep it in /tmp -- it has been wiped twice.
"""
import ctypes as C, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ZIDDLE = Path.home() / 'ziddle/ziddle-source-1787802520'
BIN = ZIDDLE / 'target/release'
INPUT = Path.home() / 'ziddle/inputs/plucks_hiss.f32'


def test_input():
    """3 s: 0.4 s of hiss, then decaying 110 Hz plucks every 0.75 s, over -76 dB hiss."""
    if not INPUT.exists():
        INPUT.parent.mkdir(parents=True, exist_ok=True)
        sr = 44100; t = np.arange(sr * 3) / sr
        x = 0.3 * np.sin(2 * np.pi * 110 * t) * np.exp(-(t % 0.75) * 3) * (t > 0.4)
        x += np.random.default_rng(2).standard_normal(len(t)) * 10 ** (-76 / 20)
        x.astype(np.float32).tofile(INPUT)
    return INPUT


def host(lib, x, knobs):
    lib.Fx_FLT_NAMLite.argtypes = [C.POINTER(C.c_size_t)]
    mem = (C.c_uint8 * (4 << 20))(); b = C.addressof(mem); d = (C.c_size_t * 2)(b, b + (4 << 20))
    p = (C.c_float * 14)(1, 0, 0, 0, 0, *[k / 100 for k in knobs], *([0.5] * (9 - len(knobs))))
    fx = (C.c_float * 16)(); src = C.c_uint(1); dst = C.c_uint(); dp = C.c_size_t(C.addressof(dst))
    ctx = (C.c_size_t * 13)()
    for k, v in [(1, p), (3, d), (5, fx), (11, dp), (12, src)]: ctx[k] = C.addressof(v)
    out = np.zeros(len(x), np.float32)
    for i in range(0, len(x) - 7, 8):
        fx[:8] = list(x[i:i + 8]); fx[8:] = list(x[i:i + 8]); lib.Fx_FLT_NAMLite(ctx); out[i:i + 8] = fx[:8]
    return out


def main():
    zdl, kdir, knobs = Path(sys.argv[1]), Path(sys.argv[2]), [float(v) for v in sys.argv[3].split(',')]
    defs = sys.argv[4:]
    inp = test_input()
    with tempfile.TemporaryDirectory() as td:
        so = Path(td) / 'host.so'
        subprocess.run(['cc', '-O2', '-ffp-contract=off', '-shared', '-fPIC', '-w', f'-I{kdir}',
                        f'-I{ROOT}/src/airwindows/common', f'-I{ROOT}/src/hardware_probes/namlite', *defs,
                        str(ROOT / 'src/hardware_probes/namlite/namlite.c'), '-o', str(so)], check=True)
        out = Path(td) / 'ti.f32'
        r = subprocess.run([str(BIN / 'namcheck'), str(zdl), str(inp), str(out), sys.argv[3]],
                           capture_output=True, text=True, check=True)
        ti = np.fromfile(out, np.float32); h = host(C.CDLL(str(so)), np.fromfile(inp, np.float32), knobs)
    n = min(len(ti), len(h))
    print([l for l in r.stdout.splitlines() if 'cycles' in l][0])
    print(f'TI (emulator) vs host: max|diff| {float(np.max(np.abs(ti[:n] - h[:n]))):.2e}')


if __name__ == '__main__':
    main()
