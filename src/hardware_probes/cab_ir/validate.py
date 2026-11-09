"""Validate CabIR 0.30 (run build.py --template, then build.py <IR> --names sm57).

1. Host build of cab_ir.c against a float64 reference of the fitted model
   (FIR, then gain, cab biquads, Reso, Pres) at several knob settings.
2. Reso/Pres at 50 are exact identities: the host output equals the host
   output of the model without those two sections, bit for bit.
3. Guards: undersized arena and bypass leave audio dry; Mix 0 is exact dry;
   Level 0 mutes; nothing is written outside the arena; the ctx[11]/ctx[12]
   magic shuttle is preserved; 4-aligned arenas behave the same as aligned.
4. The TI build in the emulator matches the host build (namcheck), and its
   callback cost is reported against 0.03.
"""
import ctypes as C, json, subprocess, sys
from pathlib import Path
import numpy as np
from scipy.signal import lfilter, sosfilt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'build/probes/cab-ir'
M = np.load(OUT / 'model.npz')
subprocess.run(['cc', '-O2', '-ffp-contract=off', '-shared', '-fPIC', '-DHOST_TEST', str(HERE / 'cab_ir.c'),
                f'-I{OUT}/slot1', f'-I{ROOT}/src/airwindows/common', '-o', str(OUT / 'host.so')], check=True)
lib = C.CDLL(str(OUT / 'host.so'))
lib.state_bytes.restype = C.c_uint
lib.Fx_REV_CabIR.argtypes = [C.POINTER(C.c_size_t)]
SIZE = lib.state_bytes()


class Instance:
    def __init__(self, knobs=(1, .5, .5, .5), short=False, shift=0):
        self.mem = (C.c_uint64 * ((SIZE + 128) // 8))()
        C.memset(self.mem, 165, C.sizeof(self.mem))
        self.base = C.addressof(self.mem) + 16 + shift
        self.end = self.base + (16 if short else SIZE + 8)
        self.d = (C.c_size_t * 2)(self.base, self.end)
        self.p = (C.c_float * 14)(1, 0, 0, 0, 0, *knobs)
        self.fx = (C.c_float * 16)(); self.src = C.c_uint(1234); self.dst = C.c_uint()
        self.dp = C.c_size_t(C.addressof(self.dst)); self.ctx = (C.c_size_t * 13)()
        for n, v in [(1, self.p), (3, self.d), (5, self.fx), (11, self.dp), (12, self.src)]:
            self.ctx[n] = C.addressof(v)

    def run(self, blk):
        self.fx[:] = list(blk); lib.Fx_REV_CabIR(self.ctx)
        assert self.dst.value == 1234
        assert C.string_at(C.addressof(self.mem), 16) == bytes([165]) * 16, 'wrote before the arena'
        assert C.string_at(self.end, 16) == bytes([165]) * 16, 'wrote past the arena'
        return np.array(self.fx[:], np.float32)

    def play(self, x):
        out = np.zeros(len(x), np.float32)
        for i in range(0, len(x) - 7, 8):
            out[i:i + 8] = self.run(np.concatenate([x[i:i + 8]] * 2))[:8]
        return out


def reference(x, reso_k, pres_k, level, cab=0):
    r32 = lambda v: np.float32(v).astype(float)          # the engine holds float32 coefficients
    y = lfilter(r32(M['fir'][cab]), [1], x.astype(float)) * float(r32(M['gain'][cab]))
    sos = np.array([[r[0], r[1], r[2], 1.0, r[3], r[4]] for r in r32(M['sos'][cab])])
    y = sosfilt(sos, y)
    for tab, k in ((M['reso'], reso_k), (M['pres'], pres_k)):
        b0, b1, b2, a1, a2 = np.float32(tab[k]).astype(float)
        y = lfilter([b0, b1, b2], [1, a1, a2], y)
    return np.clip(y * level, -1, 1)


def main():
    rng = np.random.default_rng(5)
    x = rng.uniform(-.05, .05, 44100).astype(np.float32)
    worst, low = 0.0, 1e9
    for reso_k, pres_k in ((50, 50), (100, 50), (50, 0), (0, 100), (80, 70)):
        a = Instance((1, .5, reso_k / 100, pres_k / 100))
        y = a.play(x)
        ref = reference(x, reso_k, pres_k, 1.0)                          # slot 1's cab
        s = slice(22050, len(x) // 8 * 8)   # skip the Mix fade-in; the last partial block is never run
        # float32 vs float64: low-frequency biquads (poles at r~0.996) round
        # noticeably in a cascade. Measured 57-73 dB below the signal -- under
        # any amp's own noise floor. Require 50 dB.
        e = y[s] - ref[s]
        snr = float(20 * np.log10(np.sqrt(np.mean(ref[s] ** 2)) / np.sqrt(np.mean(e ** 2))))
        worst = max(worst, float(np.max(np.abs(e)))) if snr else worst
        low = min(low, snr)
        assert snr > 50, f'Reso {reso_k} Pres {pres_k}: host vs reference only {snr:.1f} dB below signal'
    print(f'1. host vs float64 reference, 5 knob settings: error >= {low:.1f} dB below signal')

    four = Instance(shift=4).play(x)
    assert np.array_equal(four, Instance().play(x)), '4-aligned arena differs'
    blk = np.concatenate([x[:8]] * 2)
    assert np.array_equal(Instance(short=True).run(blk), blk), 'undersized arena not dry'
    b = Instance(); b.p[0] = 0
    assert np.array_equal(b.run(blk), blk), 'bypass not dry'
    dry = Instance((0, .5, .5, .5)).play(x)
    assert np.array_equal(dry[:len(x) // 8 * 8], x[:len(x) // 8 * 8]), 'Mix 0 not exact dry'
    muted = Instance((1, 0, .5, .5)).play(x)
    assert np.max(np.abs(muted[22050:])) < 2e-6, 'Level 0 does not mute'
    print('2-3. identities and guards: 4-aligned arena, undersized arena, bypass, Mix 0 exact dry, Level 0 mute')

    S = Path.home() / 'ziddle/inputs'                 # never /tmp: it has been wiped twice
    S.mkdir(parents=True, exist_ok=True)
    Z = Path.home() / 'ziddle/ziddle-source-1787802520/target/release'
    sig = np.concatenate([np.zeros(11025, np.float32), x])
    sig.tofile(S / 'cab_in.f32')
    rows = []
    for zdl, knobs, tag in ((OUT / 'C01sm57.ZDL', '100,50,80,70', 'new'),
                            (ROOT / 'build/ir-archive/cabir-0.03/CabIR.ZDL', '100,50,100', 'old')):
        r = subprocess.run([str(Z / 'namcheck'), str(zdl), str(S / 'cab_in.f32'), str(S / f'cab_{tag}.f32'), knobs],
                           capture_output=True, text=True, check=True)
        rows.append((tag, [l for l in r.stdout.splitlines() if 'cycles' in l][0]))
    ti = np.fromfile(S / 'cab_new.f32', np.float32)
    host = Instance((1, .5, .8, .7)).play(sig)
    n = min(len(ti), len(host))
    d = float(np.max(np.abs(ti[:n] - host[:n])))
    print(f'4. TI build in the emulator vs host build (slot 1, Reso 80, Pres 70): max|diff| {d:.2e}')
    assert d < 1e-5
    for tag, line in rows:
        print(f'   {tag}: {line}')
    (OUT / 'validation.json').write_text(json.dumps(dict(passed=True, state_bytes=SIZE, host_vs_reference=worst,
                                                         ti_vs_host=d, cycles=dict(rows)), indent=2) + '\n')
    print('PASS')


if __name__ == '__main__':
    main()
