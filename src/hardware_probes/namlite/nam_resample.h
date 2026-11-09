/* NAMLite: Eco's resampling (8 -> N -> 8 samples a callback) and the soft
 * output limiter. Both branch-free (docs/SAFE-DSP-RULES.md).
 *
 * Eco runs the network N times per 8-sample callback, at 44.1 kHz * N / 8.
 * Until 0.25 it sampled the input at floor(8i/N) (0,1,2,4,5,6 for N = 6:
 * uneven, which puts periodic timing error and spurs on the signal) and
 * interpolated the output linearly. Now both directions are 4-point cubic
 * (Catmull-Rom Hermite) at exact, even positions:
 *   in:  model step i of a block sits at input position 8i/N, read one input
 *        sample late so the curve's right neighbour exists;
 *   out: output sample k sits at model position kN/8, read two model steps
 *        late for the same reason.
 * Added latency ~3.7 samples. Python model of the chain with an identity
 * network (6/8, -6 dBFS sine): worst spur 1 kHz -33.5 -> -79 dB, 3 kHz
 * -22.8 -> -53 dB, 8 kHz -11 -> -24.5 dB, and 2.8 dB more level at 8 kHz.
 *
 * Positions are exact multiples of 1/N and 1/8, so index and fraction come
 * from integer arithmetic on constants (no runtime divide, no float->unsigned
 * cast). */
#ifndef NAM_RESAMPLE_H
#define NAM_RESAMPLE_H

typedef struct { float xin[2], yout[3], pad[3]; } NamEcoState;

/* Unrolls, measured TI vs host (0.26). Unrolled, the curve loops schedule well
 * (the 8-step one by 8, the N-step one by exactly N: UNROLL(8) on a loop that
 * runs 6 times gave wrong code). The copies into net.input before nam_block
 * and out of net.output after it stay rolled loops: unrolled, they moved
 * across the inlined kernel, whose restrict pointers let the compiler reorder
 * its reads of those arrays, and the output diverged from the host by 0.26. */
#define NAM_UNROLL8 _Pragma("UNROLL(8)")
#if defined(NAM_RATE_STEPS) && NAM_RATE_STEPS == 4
#define NAM_UNROLLN _Pragma("UNROLL(4)")
#elif defined(NAM_RATE_STEPS) && NAM_RATE_STEPS == 5
#define NAM_UNROLLN _Pragma("UNROLL(5)")
#elif defined(NAM_RATE_STEPS) && NAM_RATE_STEPS == 6
#define NAM_UNROLLN _Pragma("UNROLL(6)")
#elif defined(NAM_RATE_STEPS) && NAM_RATE_STEPS == 7
#define NAM_UNROLLN _Pragma("UNROLL(7)")
#else
#define NAM_UNROLLN
#endif   /* last 2 inputs, last 3 model outputs */

#pragma FUNC_ALWAYS_INLINE(nam_hermite)
static inline float nam_hermite(float ym1, float y0, float y1, float y2, float f)
{
    float c1 = 0.5f * (y1 - ym1);
    float c2 = ym1 - 2.5f * y0 + 2.0f * y1 - 0.5f * y2;
    float c3 = 0.5f * (y2 - ym1) + 1.5f * (y0 - y1);
    return ((c3 * f + c2) * f + c1) * f + y0;
}

/* 8 input samples -> N model inputs, in place. Results go to a local array
 * first: written straight into x8, the compiler had to assume a store could
 * feed the next step's reads, and ran the loop at 44 cycles a step. */
#pragma FUNC_ALWAYS_INLINE(nam_eco_down)
static inline void nam_eco_down(NamEcoState *r, float *x8, unsigned n)
{
    float e[10], o[8];
    unsigned i;
    e[0] = r->xin[0]; e[1] = r->xin[1];
    NAM_UNROLL8
    for (i = 0; i < 8u; ++i) e[2u + i] = x8[i];
    r->xin[0] = x8[6]; r->xin[1] = x8[7];
    NAM_UNROLLN
    for (i = 0; i < n; ++i) {
        unsigned a8 = 8u * i, a = a8 / n;                  /* n is a compile-time constant */
        float f = (float)(int)(a8 - a * n) * (1.0f / (float)(int)n);
        o[i] = nam_hermite(e[a], e[a + 1u], e[a + 2u], e[a + 3u], f);
    }
    for (i = 0; i < n; ++i) x8[i] = o[i];
}

/* N model outputs -> 8 output samples, in place (same local-array rule). */
#pragma FUNC_ALWAYS_INLINE(nam_eco_up)
static inline void nam_eco_up(NamEcoState *r, float *y, unsigned n)
{
    float m[11], o[8];
    unsigned k;
    m[0] = r->yout[0]; m[1] = r->yout[1]; m[2] = r->yout[2];
    for (k = 0; k < n; ++k) m[3u + k] = y[k];
    r->yout[0] = y[n - 3u]; r->yout[1] = y[n - 2u]; r->yout[2] = y[n - 1u];
    NAM_UNROLL8
    for (k = 0; k < 8u; ++k) {
        unsigned q = k * n, j = q >> 3;
        float g = (float)(int)(q & 7u) * 0.125f;
        o[k] = nam_hermite(m[j], m[j + 1u], m[j + 2u], m[j + 3u], g);
    }
    NAM_UNROLL8
    for (k = 0; k < 8u; ++k) y[k] = o[k];
}

/* Soft limiter: exact below NAM_KNEE, then d*u/(1+u) toward +-1, where
 * u = (|y| - knee) / d and d = 1 - knee: the slope stays 1 at the knee, so
 * there is no corner. Replaces the hard clip at 1.0 (0.25). */
#define NAM_KNEE 0.75f
#pragma FUNC_ALWAYS_INLINE(nam_rcp)
static inline float nam_rcp(float x)
{
#ifdef __TI_COMPILER_VERSION__
    float r = _rcpsp(x); return r * (2.0f - x * r);   /* one Newton step: ~1e-5, only above the knee */
#else
    return 1.0f / x;
#endif
}
#pragma FUNC_ALWAYS_INLINE(nam_soft)
static inline float nam_soft(float y)
{
    union { float f; unsigned u; } s, o;
    float a = NAM_ABS(y), over = 0.5f * ((a - NAM_KNEE) + NAM_ABS(a - NAM_KNEE));   /* max(a - knee, 0) */
    float u = over * (1.0f / (1.0f - NAM_KNEE));
    s.f = y;
    o.f = a - over + (1.0f - NAM_KNEE) * u * nam_rcp(1.0f + u);
    o.u |= s.u & 0x80000000u;                                                     /* y's sign */
    return o.f;
}

#endif
