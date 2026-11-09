#!/usr/bin/env python3
"""Trial: NAMLite with the convolution taps in 16-bit fixed point.

Experimental, no release output. Builds two NAMLite slot-1 files from the same
capture, the shipping float kernel and a q16 kernel, and compares them in the
emulator: cycles, and the output difference.

The q16 kernel changes only the dilated convolutions, where the time goes.
Each layer's ring holds its input v as packed 16-bit pairs, (a, c) and (e, 0),
at a per-layer scale; the taps are DOTP2 (two 16x16 products summed) into
32-bit accumulators, which add with no latency, and the result is scaled back
to float. Activation, input mix, 1x1, residual and head stay float.

  * Weight scale, per layer: the largest power of two that keeps the worst
    sum |w| * 32767 of any output under 2^31 (so the accumulator cannot
    overflow, whatever the input) and every weight within int16. Computed
    on the pedal from the float weights, one layer per callback at start-up.
  * Activation scale, per layer: from running the capture (numpy) on
    full-scale noise and sines, with x2 headroom; the ring saturates beyond.
    A release would have the loader compute this table for each capture.

    python3 tools/nam_prototype/q16_trial.py <capture.nam> <out dir>
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/nam_prototype'), str(ROOT / 'build'), str(ROOT / 'src/airwindows/common')]
from generate_block import generate_block                  # noqa: E402
import exact_rings                                          # noqa: E402
import tone_stack                                           # noqa: E402
from linker import LinkerConfig, link, params_from_manifest  # noqa: E402

D = [1, 3, 7, 17, 41, 101, 239, 1, 3, 7, 17, 41, 101, 239, 1, 13, 1, 3, 7, 17, 41, 101, 239]
K = [6] * 14 + [15, 15] + [6] * 7
TI = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
TONE_PARAMS = [dict(name='Bass', max=100, default=50), dict(name='Mid', max=100, default=50),
               dict(name='Treb', max=100, default=50), dict(name='Gate', max=100, default=0)]


def model_weights(path):
    root = json.loads(Path(path).read_text())
    m = root['config']['submodels'][0]['model'] if root['architecture'] == 'SlimmableContainer' else root
    return np.asarray(m['weights'], np.float64)


def ranges(w, x):
    """max |v| entering each layer, over the signal x (numpy, whole signal per layer)."""
    at = 0

    def take(n):
        nonlocal at
        v = w[at:at + n]; at += n; return v
    v = np.outer(take(3), x)
    out = []
    for k, d in zip(K, D):
        cw = take(9 * k).reshape(3, 3, k); b = take(3); mix = take(3); rw = take(9).reshape(3, 3); rb = take(3)
        out.append(float(np.abs(v).max()))
        z = b[:, None] + mix[:, None] * x[None, :]
        for t in range(k):
            s = (k - 1 - t) * d
            vs = np.zeros_like(v); vs[:, s:] = v[:, :v.shape[1] - s] if s else v
            z += cw[:, :, t] @ vs
        z = np.where(z < 0, 0.01 * z, z)
        v = v + rb[:, None] + rw @ z
    return out


def calibration_signal():
    rng = np.random.default_rng(1)
    n = 1 << 16
    w = rng.standard_normal(n); f = np.fft.rfftfreq(n); W = np.fft.rfft(w); W[1:] /= np.sqrt(f[1:]); p = np.fft.irfft(W, n)
    t = np.arange(n) / 44100
    sig = [p / np.abs(p).max(), np.sin(2 * np.pi * 82 * t), np.sin(2 * np.pi * 1000 * t), np.sign(np.sin(2 * np.pi * 110 * t))]
    return np.concatenate(sig)                              # |x| <= 1: NAMLite clips its input there


Q16_BLOCK = r'''
/* ---- q16 taps (tools/nam_prototype/q16_trial.py) ------------------------- */
#define NAM_Q_RINGS __RINGS__u                 /* words: 2 per slot, (n + 8) slots per layer */
#define NAM_Q_HEAD  (NAM_Q_RINGS)              /* 102 floats: the head's 3 x 34 history */
#define NAM_Q_W     (NAM_Q_HEAD + 102u)        /* packed weights: 6 words a tap */
#define NAM_Q_INV   (NAM_Q_W + __QW__u)        /* per layer 2^-(as + ws), float */
#define NAM_Q_READY (NAM_Q_INV + 23u)          /* layers prepared so far */
static const float nam_qact[23] = {__QACT__};  /* per layer 2^as: v -> int16 */

#ifndef __TI_COMPILER_VERSION__                /* host build: the three intrinsics */
static inline int _dotp2(int a, int b) { return (short)(a >> 16) * (short)(b >> 16) + (short)a * (short)b; }
static inline int nam_sat16(int v) { return v > 32767 ? 32767 : v < -32768 ? -32768 : v; }
static inline unsigned _spack2(int hi, int lo) { return ((unsigned)nam_sat16(hi) << 16) | ((unsigned)nam_sat16(lo) & 0xFFFFu); }
static inline int _spint(float f) { return (int)(f >= 0 ? f + 0.5f : f - 0.5f); }
#endif

/* Pack one layer's conv weights into int16 pairs, at the largest power-of-two
 * scale that keeps any output's accumulator under 2^31. One layer a call. */
#pragma FUNC_ALWAYS_INLINE(nam_q_prepare)
static inline void nam_q_prepare(NamState *s, unsigned layer)
{
    unsigned * restrict hw = (unsigned *)s->history;
    const float *w = nam_weights + 3;
    unsigned l, t, o, at = 0;
    float worst = 1e-12f, wmax = 1e-12f, sc = 1.0f;
    for (l = 0; l < layer; ++l) { w += 9u * nam_kernels[l] + 18u; at += 6u * nam_kernels[l]; }
    {
        unsigned k = nam_kernels[layer];
        for (o = 0; o < 3u; ++o) {
            float sum = 0.0f;
            for (t = 0; t < k; ++t) {          /* pedal order [tap][out][in] (nam_loader.js reorder) */
                unsigned j;
                for (j = 0; j < 3u; ++j) { float a = w[9u * t + 3u * o + j]; a = a < 0 ? -a : a; sum += a; if (a > wmax) wmax = a; }
            }
            if (sum > worst) worst = sum;
        }
        while (worst * sc * 2.0f * 32768.0f < 2147483647.0f && wmax * sc * 2.0f < 32767.0f && sc < 1073741824.0f) sc *= 2.0f;
        for (t = 0; t < k; ++t)
            for (o = 0; o < 3u; ++o) {
                int a = _spint(w[9u * t + 3u * o] * sc), c = _spint(w[9u * t + 3u * o + 1u] * sc);
                int e = _spint(w[9u * t + 3u * o + 2u] * sc);
                hw[NAM_Q_W + at + 6u * t + 2u * o] = _spack2(a, c);
                hw[NAM_Q_W + at + 6u * t + 2u * o + 1u] = _spack2(e, 0);
            }
        {   /* 1 / (sc * act), both powers of two: negate the exponent (no divide helper) */
            union { float f; unsigned u; } pw, iv;
            pw.f = sc * nam_qact[layer]; iv.u = 0x7F000000u - pw.u;
            ((float *)hw)[NAM_Q_INV + layer] = iv.f;
        }
    }
}

#pragma FUNC_ALWAYS_INLINE(nam_block)
static inline void nam_block(NamState *s, unsigned count)
{
    const float * restrict w = nam_weights;
    const float * restrict input = s->input;
    float * restrict output = s->output;
    float * restrict v = s->v;
    float * restrict sum = s->sum;
    float * restrict zbuf = s->z;
    unsigned * restrict hw = (unsigned *)s->history;
    float * restrict head = (float *)s->history + NAM_Q_HEAD;
    const unsigned * restrict qw = hw + NAM_Q_W;
    unsigned pos = s->pos;
    unsigned i, layer, t, off = 0, p, q, qat = 0;
    if (hw[NAM_Q_READY] < 23u) {               /* start-up: one layer's weights a callback, silence */
        nam_q_prepare(s, hw[NAM_Q_READY]);
        hw[NAM_Q_READY]++;
        for (i = 0; i < count; ++i) output[i] = 0.0f;
        return;
    }
    for (i = 0; i < count; i++) {
        float x = input[i];
        v[i] = x * w[0]; v[10 + i] = x * w[1]; v[20 + i] = x * w[2];
        sum[i] = 0; sum[10 + i] = 0; sum[20 + i] = 0;
    }
    w += 3;
    for (layer = 0; layer < 23; layer++) {
        unsigned n = nam_sizes[layer], k = nam_kernels[layer], d = nam_dilations[layer];
        unsigned stride = 2u * (n + 8u);
        unsigned * restrict h = hw + off;
        unsigned base = s->lpos[layer];
        const float *b = w + 9 * k;
        const float act = nam_qact[layer], inv = ((const float *)hw)[NAM_Q_INV + layer];
        if (base >= n) base = 0;
        {   /* write v as int16 pairs, without wrapping: at most two runs */
            unsigned first = n - base; if (first > count) first = count;
            for (i = 0; i < first; i++) { p = 2u * (base + i);
                h[p] = _spack2(_spint(v[i] * act), _spint(v[10 + i] * act)); h[p + 1] = _spack2(_spint(v[20 + i] * act), 0); }
            for (i = first; i < count; i++) { p = 2u * (base + i - n);
                h[p] = _spack2(_spint(v[i] * act), _spint(v[10 + i] * act)); h[p + 1] = _spack2(_spint(v[20 + i] * act), 0); }
            if (base < 8u || base + count > n)
                for (i = 0; i < 16; i++) h[2u * n + i] = h[i];
        }
        if (count == 8u) {
            unsigned g;
            for (g = 0; g < 8u; g += 4u) {     /* samples 0..3, then 4..7 */
                const unsigned * restrict wt = qw + qat;
                int Z00 = 0, Z01 = 0, Z02 = 0, Z03 = 0, Z10 = 0, Z11 = 0, Z12 = 0, Z13 = 0, Z20 = 0, Z21 = 0, Z22 = 0, Z23 = 0;
                for (t = 0; t < k; t++) {
                    int A0 = (int)wt[0], E0 = (int)wt[1], A1 = (int)wt[2], E1 = (int)wt[3], A2 = (int)wt[4], E2 = (int)wt[5];
                    int x = (int)base - (int)((k - 1 - t) * d);
                    unsigned st0 = (unsigned)(x + ((int)n & (x >> 31)));
                    const unsigned * restrict hp = h + 2u * (st0 + g);
                    { int ac = (int)hp[0], e = (int)hp[1];
                      Z00 += _dotp2(A0, ac) + _dotp2(E0, e); Z10 += _dotp2(A1, ac) + _dotp2(E1, e); Z20 += _dotp2(A2, ac) + _dotp2(E2, e); }
                    { int ac = (int)hp[2], e = (int)hp[3];
                      Z01 += _dotp2(A0, ac) + _dotp2(E0, e); Z11 += _dotp2(A1, ac) + _dotp2(E1, e); Z21 += _dotp2(A2, ac) + _dotp2(E2, e); }
                    { int ac = (int)hp[4], e = (int)hp[5];
                      Z02 += _dotp2(A0, ac) + _dotp2(E0, e); Z12 += _dotp2(A1, ac) + _dotp2(E1, e); Z22 += _dotp2(A2, ac) + _dotp2(E2, e); }
                    { int ac = (int)hp[6], e = (int)hp[7];
                      Z03 += _dotp2(A0, ac) + _dotp2(E0, e); Z13 += _dotp2(A1, ac) + _dotp2(E1, e); Z23 += _dotp2(A2, ac) + _dotp2(E2, e); }
                    wt += 6;
                }
                zbuf[g] = b[0] + (float)Z00 * inv; zbuf[10 + g] = b[1] + (float)Z10 * inv; zbuf[20 + g] = b[2] + (float)Z20 * inv;
                zbuf[g + 1] = b[0] + (float)Z01 * inv; zbuf[11 + g] = b[1] + (float)Z11 * inv; zbuf[21 + g] = b[2] + (float)Z21 * inv;
                zbuf[g + 2] = b[0] + (float)Z02 * inv; zbuf[12 + g] = b[1] + (float)Z12 * inv; zbuf[22 + g] = b[2] + (float)Z22 * inv;
                zbuf[g + 3] = b[0] + (float)Z03 * inv; zbuf[13 + g] = b[1] + (float)Z13 * inv; zbuf[23 + g] = b[2] + (float)Z23 * inv;
            }
        } else {
            for (i = 0; i < count; i++) {
                const unsigned * restrict wt = qw + qat;
                int Z0 = 0, Z1 = 0, Z2 = 0;
                for (t = 0; t < k; t++) {
                    unsigned st0 = base + n - (k - 1 - t) * d; if (st0 >= n) st0 -= n;
                    q = 2u * (st0 + i);
                    { int ac = (int)h[q], e = (int)h[q + 1];
                      Z0 += _dotp2((int)wt[0], ac) + _dotp2((int)wt[1], e); Z1 += _dotp2((int)wt[2], ac) + _dotp2((int)wt[3], e);
                      Z2 += _dotp2((int)wt[4], ac) + _dotp2((int)wt[5], e); }
                    wt += 6;
                }
                zbuf[i] = b[0] + (float)Z0 * inv; zbuf[10 + i] = b[1] + (float)Z1 * inv; zbuf[20 + i] = b[2] + (float)Z2 * inv;
            }
        }
        for (i = 0; i < count; i++) {
            float x = input[i];
            float z0 = zbuf[i] + b[3] * x, z1 = zbuf[10 + i] + b[4] * x, z2 = zbuf[20 + i] + b[5] * x;
            if (z0 < 0) z0 *= .01f; if (z1 < 0) z1 *= .01f; if (z2 < 0) z2 *= .01f;
            sum[i] += z0; sum[10 + i] += z1; sum[20 + i] += z2;
            v[i] += b[15] + b[6] * z0 + b[7] * z1 + b[8] * z2;
            v[10 + i] += b[16] + b[9] * z0 + b[10] * z1 + b[11] * z2;
            v[20 + i] += b[17] + b[12] * z0 + b[13] * z1 + b[14] * z2;
        }
        base += count; if (base >= n) base -= n; s->lpos[layer] = base;
        w = b + 18; off += stride; qat += 6u * k;
    }
    for (i = 0; i < count; i++) {
        p = (pos + i) & 31u;
        head[p] = sum[i]; head[34 + p] = sum[10 + i];
        head[68 + p] = sum[20 + i]; output[i] = w[48];
    }
    for (t = 0; t < 16; t++) {
        float w0 = w[t], w1 = w[16 + t], w2 = w[32 + t];
        for (i = 0; i < count; i++) {
            q = (pos + i - (15 - t)) & 31u;
            float y = output[i];
            y += w0 * head[q]; y += w1 * head[q + 34]; y += w2 * head[q + 68];
            output[i] = y;
        }
    }
    for (i = 0; i < count; i++) output[i] *= w[49];
    s->pos += count;
}
'''


def q16_header(float_header: Path, act_shift):
    src = float_header.read_text()
    pre, _ = src.split('#pragma FUNC_ALWAYS_INLINE(nam_block)', 1)
    sizes = [int(v) for v in pre.split('nam_sizes[] = {')[1].split('}')[0].split(',')]
    rings = sum(2 * (n + 8) for n in sizes)
    qw = 6 * sum(K)
    total = rings + 102 + qw + 23 + 1
    old_hist = pre.split('history[')[1].split(']')[0]
    pre = pre.replace(f'history[{old_hist}]', f'history[{total}]')
    return (pre + Q16_BLOCK.replace('__RINGS__', str(rings)).replace('__QW__', str(qw))
            .replace('__QACT__', ','.join(f'{2.0 ** a!r}f' for a in act_shift)))


def compile_and_link(work, out, steps=8):
    obj = work / 'namlite.obj'
    subprocess.run([str(TI / 'bin/cl6x'), '--c99', '-O2', '-mv6740', '--abi=eabi', '--mem_model:data=far',
                    '--fp_mode=strict', '--fp_reassoc=off', '-DNAM_TONE_STACK', '-DNAM_GATE', '-DNAM_FAST_IO',
                    *([f'-DNAM_RATE_STEPS={steps}'] if steps < 8 else []),
                    f'--include_path={TI}/include', f'--include_path={ROOT}/src/airwindows/common',
                    f'--include_path={ROOT}/src/hardware_probes/namlite', f'--include_path={work}',
                    '--keep_asm', f'--asm_directory={work}', '-c',
                    str(ROOT / 'src/hardware_probes/namlite/namlite.c'), f'--output_file={obj}'], check=True, timeout=900)
    m = json.loads((ROOT / 'src/hardware_probes/namlite/manifest.json').read_text())
    link(LinkerConfig(effect_name='NAMQ1', audio_func_name=m['audio_func_name'], gid=8, fxid=900,
                      params=params_from_manifest(m['params'] + TONE_PARAMS), obj_path=obj, output_path=out,
                      fxid_version=b'0.25', materialize_init=True, use_object_edit_handlers=False,
                      synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                      knob3_blob_path=str(work / 'unused'), dsp_cost=194))


def main():
    cap, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    fl = out / 'float'; q16 = out / 'q16'
    for d in (fl, q16):
        if d.exists():
            shutil.rmtree(d)
    generate_block(cap, fl)
    exact_rings.apply(fl, interleave=True, regacc=True, extra_counts=())
    tone_stack.write_table(fl, half=True)
    shutil.copytree(fl, q16)
    r = ranges(model_weights(cap), calibration_signal())
    act = [int(np.floor(np.log2(32767 / (2.0 * max(m, 1e-6))))) for m in r]
    (q16 / 'nam_kernel_pedal.h').write_text(q16_header(fl / 'nam_kernel_pedal.h', act))
    print('activation peaks per layer:', ' '.join(f'{m:.2f}' for m in r))
    print('activation shifts:', act)
    compile_and_link(fl, out / 'float.ZDL')
    compile_and_link(q16, out / 'q16.ZDL')
    print('built', out / 'float.ZDL', out / 'q16.ZDL')


if __name__ == '__main__':
    main()
