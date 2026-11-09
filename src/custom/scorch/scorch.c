/*
 * scorch.c -- Scorch: aggressive high-gain amp + cab, MS-70CDR.
 *
 * Pedal port of tools/audio_preview/renderers/scorch.py. 2 knobs:
 *   Gain  (params[5]) - preamp gain / distortion amount
 *   Level (params[6]) - output level
 * The tone stack and cab are baked.
 *
 * Cab note: the desktop version convolves a 256-tap cab IR. On the pedal a
 * static FIR array would force a code->data relocation (a freeze risk per the
 * safe-DSP rules), so the cab+tone voicing is baked as 5 cascaded biquads
 * whose coefficients are scalar LITERAL constants (which compile to
 * immediates, like every other effect here) -- "cab as EQ". Lower fidelity
 * than a true IR, but load-safe and a common amp-sim approach.
 *
 * Safe-DSP: no math lib (cubic soft-clip, one-pole + biquad filters with
 * literal coefficients), no runtime divide, no static arrays, no big buffer.
 * Tiny persistent state in the ctx[3] arena. ctx[11]/ctx[12] preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "scorch_params.h"

#ifndef SCORCH_AUDIO_FUNC
#define SCORCH_AUDIO_FUNC Fx_DRV_Scorch
#endif

#define SCORCH_DO_PRAGMA(x) _Pragma(#x)
#define SCORCH_EXPAND_PRAGMA(x) SCORCH_DO_PRAGMA(x)
#define SCORCH_CODE_SECTION(f) SCORCH_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

SCORCH_CODE_SECTION(SCORCH_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define SC_MAGIC   0x53435243u   /* 'SCRC' */
#define SC_VERSION 1u

#define SC_HP_COEF  0.0135f      /* pre high-pass ~95 Hz */
#define SC_LP_COEF  0.575f       /* interstage low-pass ~6 kHz */
#define SC_WET_TRIM   0.55f   /* by-ear level match against the rest of the pack */
#define SC_BIAS     0.18f

/* Baked cab+tone biquads (b0,b1,b2,a1,a2), generated offline. */
#define SC_B0_0  9.91473181e-01f
#define SC_B1_0 -1.98294636e+00f
#define SC_B2_0  9.91473181e-01f
#define SC_A1_0 -1.98287365e+00f
#define SC_A2_0  9.83019070e-01f

#define SC_B0_1  1.00220459e+00f
#define SC_B1_1 -1.97658218e+00f
#define SC_B2_1  9.74720977e-01f
#define SC_A1_1 -1.97663232e+00f
#define SC_A2_1  9.76875422e-01f

#define SC_B0_2  9.63849779e-01f
#define SC_B1_2 -1.84583677e+00f
#define SC_B2_2  8.91205171e-01f
#define SC_A1_2 -1.84583677e+00f
#define SC_A2_2  8.55054950e-01f

#define SC_B0_3  1.09539998e+00f
#define SC_B1_3 -1.45840163e+00f
#define SC_B2_3  5.78386694e-01f
#define SC_A1_3 -1.45840163e+00f
#define SC_A2_3  6.73786671e-01f

#define SC_B0_4  8.31598699e-02f
#define SC_B1_4  1.66319740e-01f
#define SC_B2_4  8.31598699e-02f
#define SC_A1_4 -1.03517121e+00f
#define SC_A2_4  3.67810689e-01f

typedef struct ScorchState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t pad;

    float hp, lp;
    float s1a, s2a, s1b, s2b, s1c, s2c, s1d, s2d, s1e, s2e;
} ScorchState;

static inline float sc_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

static inline float sc_bq(float x, float b0, float b1, float b2, float a1, float a2,
                          float *s1, float *s2)
{
    float y = b0 * x + *s1;
    *s1 = b1 * x - a1 * y + *s2;
    *s2 = b2 * x - a2 * y;
    return y;
}

void SCORCH_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u) return;
    if (end - base < (uintptr_t)sizeof(ScorchState)) return;

    ScorchState *st = (ScorchState *)base;
    if (st->magic != SC_MAGIC || st->version != SC_VERSION || !st->initialized) {
        st->magic = SC_MAGIC;
        st->version = SC_VERSION;
        st->hp = st->lp = 0.0f;
        st->s1a = st->s2a = st->s1b = st->s2b = st->s1c = st->s2c = 0.0f;
        st->s1d = st->s2d = st->s1e = st->s2e = 0.0f;
        st->initialized = 1u;
    }

    float gain  = zoom_param_norm01(params[SCORCH_GAIN_SLOT], SCORCH_GAIN_DEFAULT_NORM);
    float level = zoom_param_norm01(params[SCORCH_MIX_SLOT], SCORCH_MIX_DEFAULT_NORM);

    float pre = 1.0f + gain * 45.0f;
    float g2  = 1.0f + gain * 6.0f;
    /* Mix is now a dry/wet crossfade, and the wet path runs at unity. The old
     * law was 0.08 + level*0.42, i.e. a gain that TOPPED OUT AT 0.5 -- Scorch
     * could never reach unity however far you turned it, which is a large part
     * of why levels across the pack did not match. */
    float wetLvl = level;
    float dryLvl = 1.0f - level;
    float biasOut = sc_soft(SC_BIAS);

    float hp = st->hp, lp = st->lp;
    float s1a = st->s1a, s2a = st->s2a, s1b = st->s1b, s2b = st->s2b;
    float s1c = st->s1c, s2c = st->s2c, s1d = st->s1d, s2d = st->s2d;
    float s1e = st->s1e, s2e = st->s2e;

    int i;
    for (i = 0; i < 8; i++) {
        float in = 0.5f * (fxBuf[i] + fxBuf[i + 8]);

        /* pre high-pass (tighten) */
        hp += SC_HP_COEF * (in - hp);
        float x = (in - hp) * pre;

        /* stage 1 asymmetric soft clip */
        x = sc_soft(x + SC_BIAS) - biasOut;
        /* interstage low-pass */
        lp += SC_LP_COEF * (x - lp);
        x = lp;
        /* stage 2 + 3 */
        x = sc_soft(x * g2);
        x = sc_soft(x * 1.6f);

        /* baked cab + tone (5 biquads) */
        x = sc_bq(x, SC_B0_0, SC_B1_0, SC_B2_0, SC_A1_0, SC_A2_0, &s1a, &s2a);
        x = sc_bq(x, SC_B0_1, SC_B1_1, SC_B2_1, SC_A1_1, SC_A2_1, &s1b, &s2b);
        x = sc_bq(x, SC_B0_2, SC_B1_2, SC_B2_2, SC_A1_2, SC_A2_2, &s1c, &s2c);
        x = sc_bq(x, SC_B0_3, SC_B1_3, SC_B2_3, SC_A1_3, SC_A2_3, &s1d, &s2d);
        x = sc_bq(x, SC_B0_4, SC_B1_4, SC_B2_4, SC_A1_4, SC_A2_4, &s1e, &s2e);

        /* Wet trim before the crossfade. A high-gain amp saturates, so its
         * output RMS sits near the clip ceiling almost regardless of input --
         * blending it in at a literal 1.0 would make Scorch far louder than
         * every other effect at the same Mix. This is a by-ear calibration
         * point, not a derived constant. */
        x = x * SC_WET_TRIM;
        float out = dryLvl * in + wetLvl * x;
        if (out > 1.0f) out = 1.0f;
        else if (out < -1.0f) out = -1.0f;

        fxBuf[i]     = out;
        fxBuf[i + 8] = out;
    }

    st->hp = hp; st->lp = lp;
    st->s1a = s1a; st->s2a = s2a; st->s1b = s1b; st->s2b = s2b;
    st->s1c = s1c; st->s2c = s2c; st->s1d = s1d; st->s2d = s2d;
    st->s1e = s1e; st->s2e = s2e;
}
