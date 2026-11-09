/* CabIR 0.30 -- one cabinet per effect file, like a NAM capture: a 32-tap
 * FIR plus a cascade of biquads fitted to the whole IR (fit.py / the loader
 * page), instead of the first 256 taps of it. The loader writes cab_fir /
 * cab_sos / cab_gain into one of 16 slot templates; code never changes.
 * (0.20 held a bank of 8 behind a Cab knob: a patch stored a knob position,
 * so reordering the bank silently changed which cab a patch played.)
 *
 * About a quarter of 0.03's multiplies, and closer to the source IR: the
 * biquads carry the broad cab shape (low resonance, high roll-off, mid
 * bumps) that a 5.8 ms truncation cannot hold, the FIR the fine detail.
 * Reso and Pres are two more biquads (knob 50 = exact identity).
 *
 * Mono wet from the L/R average (NAM's output is mono anyway); dry stays
 * stereo. No writable globals: state lives in the ctx[3] arena.
 *
 * Loop rules from docs/SAFE-DSP-RULES.md and the NAM work: every loop is
 * predicate-free -- the range check is OR'd into a flag and acted on between
 * loops, and the output clip is arithmetic -- so pipelining them is safe. */
#include <stdint.h>
#include "zoom_params.h"
#include "cab_data.h"
#if CAB_NBQ != 6
#error "the two 4-biquad loops below are written for 6 cab biquads + Reso + Pres"
#endif

#ifdef __TI_COMPILER_VERSION__
#define CAB_ABS(x) _fabsf(x)      /* ABSSP intrinsic, no library call */
#else
#include <math.h>
#define CAB_ABS(x) fabsf(x)
#endif
#define MAGIC 0x43414236u
#define NZ (2 * (CAB_NBQ + 2))
#define HIST (CAB_TAPS - 1 + 8)

typedef struct {
    unsigned magic, pad;
    float mix, level;
    float z[NZ];            /* biquad states: cab cascade, then Reso, Pres */
    float buf[HIST];        /* last CAB_TAPS-1 inputs, then this block's 8 */
} State;

#pragma FUNC_ALWAYS_INLINE(cab_bq)
static inline float cab_bq(const float *c, float *z, float u)
{
    float o = c[0] * u + z[0];
    z[0] = c[1] * u - c[3] * o + z[1];
    z[1] = c[2] * u - c[4] * o;
    return o;
}

/* Signed int on purpose: float->unsigned pulls in __c6xabi_fixfu. */
#pragma FUNC_ALWAYS_INLINE(cab_row)
static inline const float *cab_row(const float (*t)[5], float norm)
{
    int k = (int)(norm * 100.0f + 0.5f);
    if (k < 0) k = 0;
    if (k > 100) k = 100;
    return t[k];
}

#pragma CODE_SECTION(Fx_REV_CabIR, ".audio")
void Fx_REV_CabIR(uintptr_t *ctx)
{
    unsigned *src = (unsigned *)ctx[12], *dst = *(unsigned **)ctx[11];
    uintptr_t *d = (uintptr_t *)ctx[3];
    float *p = (float *)ctx[1], *fx = (float *)ctx[5];
    unsigned i, t, bad = 0;
    *dst = *src;
    if (!d || !d[0] || d[1] <= d[0] || d[1] - d[0] < 8) return;
    uintptr_t base = (d[0] + 7) & ~(uintptr_t)7;
    if (d[1] - base < sizeof(State)) return;
    State *s = (State *)base;
    if (p[0] < .5f) { s->magic = 0; return; }
    if (s->magic != MAGIC) {
        s->magic = MAGIC; s->mix = 0; s->level = 1;
        for (i = 0; i < NZ; ++i) s->z[i] = 0;
        for (i = 0; i < HIST; ++i) s->buf[i] = 0;
    }
    /* `zero` is 0 at run time (magic was just set) but opaque to the compiler.
     * Indexing the coefficients with it stops the compiler from treating
     * this cab's values as known and hoisting all 40 biquad coefficients into
     * registers: that made the 8-biquad loop unschedulable (register pressure
     * 34-44 at every ii) and cost +460 cycles once the Cab knob was gone. */
    const unsigned zero = s->magic - MAGIC;
    const float * restrict fir = cab_fir + zero;
    const float (*sos)[5] = cab_sos + zero;
    const float gain = cab_gain[zero];
    float mix = zoom_param_norm01(p[5], 1), level = 2 * zoom_param_norm01(p[6], .5f);
    const float *reso = cab_row(cab_reso, zoom_param_norm01(p[7], .5f));
    const float *pres = cab_row(cab_pres, zoom_param_norm01(p[8], .5f));

    float * restrict b = s->buf;
    const float * restrict in = fx;
    for (i = 0; i < 8u; ++i) b[CAB_TAPS - 1 + i] = .5f * (in[i] + in[i + 8]);

    /* FIR, taps outer and the 8 samples in registers: one short loop instead
     * of eight, no wrap (the history is linear and slid below). */
    float y0 = 0, y1 = 0, y2 = 0, y3 = 0, y4 = 0, y5 = 0, y6 = 0, y7 = 0;
    for (t = 0; t < CAB_TAPS; ++t) {
        const float w = fir[t];
        const float * restrict x = b + (CAB_TAPS - 1) - t;
        y0 += w * x[0]; y1 += w * x[1]; y2 += w * x[2]; y3 += w * x[3];
        y4 += w * x[4]; y5 += w * x[5]; y6 += w * x[6]; y7 += w * x[7];
    }
    for (i = 0; i < CAB_TAPS - 1; ++i) b[i] = b[i + 8];

    float y[8];
    y[0] = y0; y[1] = y1; y[2] = y2; y[3] = y3; y[4] = y4; y[5] = y5; y[6] = y6; y[7] = y7;
    /* One pass over the 8 samples through all 8 biquads, every state in a
     * local. (0.10 had the states in memory: that version never pipelined --
     * register pressure 35-44 at every ii -- and ran serially; two passes of
     * four pipelined but paid two start-ups.) */
    if (reso == cab_reso[50] && pres == cab_pres[50]) {
        /* Reso and Pres both at 50: exact identities once their state is zero,
         * so run the 6 cab biquads only (for chains that shape tone in NAM). */
        const float *z = s->z;
        float a0 = z[0], a1 = z[1], a2 = z[2], a3 = z[3], a4 = z[4], a5 = z[5], a6 = z[6], a7 = z[7];
        float b0 = z[8], b1 = z[9], b2 = z[10], b3 = z[11];
        const float *c0 = sos[0], *c1 = sos[1], *c2 = sos[2], *c3 = sos[3], *c4 = sos[4], *c5 = sos[5];
        for (i = 0; i < 8u; ++i) {
            float v = y[i] * gain, o;
            o = c0[0] * v + a0; a0 = c0[1] * v - c0[3] * o + a1; a1 = c0[2] * v - c0[4] * o; v = o;
            o = c1[0] * v + a2; a2 = c1[1] * v - c1[3] * o + a3; a3 = c1[2] * v - c1[4] * o; v = o;
            o = c2[0] * v + a4; a4 = c2[1] * v - c2[3] * o + a5; a5 = c2[2] * v - c2[4] * o; v = o;
            o = c3[0] * v + a6; a6 = c3[1] * v - c3[3] * o + a7; a7 = c3[2] * v - c3[4] * o; v = o;
            o = c4[0] * v + b0; b0 = c4[1] * v - c4[3] * o + b1; b1 = c4[2] * v - c4[4] * o; v = o;
            o = c5[0] * v + b2; b2 = c5[1] * v - c5[3] * o + b3; b3 = c5[2] * v - c5[4] * o; v = o;
            bad |= (unsigned)(v < -16.0f) | (unsigned)(v > 16.0f) | (unsigned)(v != v);
            y[i] = v;
        }
        s->z[0] = a0; s->z[1] = a1; s->z[2] = a2; s->z[3] = a3; s->z[4] = a4; s->z[5] = a5; s->z[6] = a6; s->z[7] = a7;
        s->z[8] = b0; s->z[9] = b1; s->z[10] = b2; s->z[11] = b3;
        s->z[12] = 0; s->z[13] = 0; s->z[14] = 0; s->z[15] = 0;
    } else {
        const float *z = s->z;
        float a0 = z[0], a1 = z[1], a2 = z[2], a3 = z[3], a4 = z[4], a5 = z[5], a6 = z[6], a7 = z[7];
        float b0 = z[8], b1 = z[9], b2 = z[10], b3 = z[11], b4 = z[12], b5 = z[13], b6 = z[14], b7 = z[15];
        const float *c0 = sos[0], *c1 = sos[1], *c2 = sos[2], *c3 = sos[3];
        const float *c4 = sos[4], *c5 = sos[5], *c6 = reso, *c7 = pres;
        for (i = 0; i < 8u; ++i) {
            float v = y[i] * gain, o;
            o = c0[0] * v + a0; a0 = c0[1] * v - c0[3] * o + a1; a1 = c0[2] * v - c0[4] * o; v = o;
            o = c1[0] * v + a2; a2 = c1[1] * v - c1[3] * o + a3; a3 = c1[2] * v - c1[4] * o; v = o;
            o = c2[0] * v + a4; a4 = c2[1] * v - c2[3] * o + a5; a5 = c2[2] * v - c2[4] * o; v = o;
            o = c3[0] * v + a6; a6 = c3[1] * v - c3[3] * o + a7; a7 = c3[2] * v - c3[4] * o; v = o;
            o = c4[0] * v + b0; b0 = c4[1] * v - c4[3] * o + b1; b1 = c4[2] * v - c4[4] * o; v = o;
            o = c5[0] * v + b2; b2 = c5[1] * v - c5[3] * o + b3; b3 = c5[2] * v - c5[4] * o; v = o;
            o = c6[0] * v + b4; b4 = c6[1] * v - c6[3] * o + b5; b5 = c6[2] * v - c6[4] * o; v = o;
            o = c7[0] * v + b6; b6 = c7[1] * v - c7[3] * o + b7; b7 = c7[2] * v - c7[4] * o; v = o;
            bad |= (unsigned)(v < -16.0f) | (unsigned)(v > 16.0f) | (unsigned)(v != v);
            y[i] = v;
        }
        s->z[0] = a0; s->z[1] = a1; s->z[2] = a2; s->z[3] = a3; s->z[4] = a4; s->z[5] = a5; s->z[6] = a6; s->z[7] = a7;
        s->z[8] = b0; s->z[9] = b1; s->z[10] = b2; s->z[11] = b3; s->z[12] = b4; s->z[13] = b5; s->z[14] = b6; s->z[15] = b7;
    }
    if (bad) { s->magic = 0; return; }       /* clear and start again next callback */

    /* Predicate-free, so it may pipeline safely: the range check already ran
     * (bad, above), and the +-1 clip is (|v+1| - |v-1|) / 2 -- ABSSP, no
     * compare-and-select. Mix 0 stays exact dry (m == 0 exactly). */
    {
        float m = s->mix, lv = s->level;
        for (i = 0; i < 8u; ++i) {
            float l = fx[i], r = fx[i + 8], v = y[i];
            m += .002f * (mix - m);
            lv += .002f * (level - lv);
            v *= lv;
            v = .5f * (CAB_ABS(v + 1.0f) - CAB_ABS(v - 1.0f));
            fx[i] = l + m * (v - l);
            fx[i + 8] = r + m * (v - r);
        }
        s->mix = m; s->level = lv;
    }
}

#ifdef HOST_TEST
unsigned state_bytes(void) { return sizeof(State); }
#endif
