/*
 * corrupt.c -- Corrupt: Data Corrupter-style PLL square synth, MS-70CDR.
 *
 * Pedal port (v1) of tools/audio_preview/renderers/corrupt.py. The desktop
 * version tracks pitch with autocorrelation/FFT, which is far too heavy for
 * the pedal runtime, so this uses a lightweight ZERO-CROSSING tracker: a
 * low-passed copy of the input is watched for rising zero crossings, the
 * interval gives the period, and a reciprocal approximation turns that into
 * the oscillator phase increment (no runtime divide). Tracking is crude and
 * octave-jumps on ambiguous input -- which is on-brand for a Data Corrupter.
 *
 * v1 voices: square MASTER (unison) + square SUB (one octave down), gated by
 * an envelope follower so the synth tracks picking dynamics. Harmony/FM are
 * deferred. 2 knobs:
 *   Sub (params[5]) - subharmonic level
 *   Mix (params[6]) - dry/synth blend
 *
 * Safe-DSP: no math lib (squares are compares; reciprocal is a Newton
 * approximation), no runtime divide, no modulo. Small persistent state lives
 * in the ctx[3] arena (no large buffer needed). ctx[11]/ctx[12] preserved.
 *
 * NOTE: gid=3 (Drive). On MS-70CDR a custom Drive effect may only appear in
 * the on-device browser if at least one stock Drive effect is also installed.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "corrupt_params.h"

#ifndef CORRUPT_AUDIO_FUNC
#define CORRUPT_AUDIO_FUNC Fx_DRV_Corrupt
#endif

#define CORRUPT_DO_PRAGMA(x) _Pragma(#x)
#define CORRUPT_EXPAND_PRAGMA(x) CORRUPT_DO_PRAGMA(x)
#define CORRUPT_CODE_SECTION(f) CORRUPT_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

CORRUPT_CODE_SECTION(CORRUPT_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define CR_MAGIC   0x43525054u   /* 'CRPT' */
#define CR_VERSION 2u

#define CR_LP_COEF  0.10f        /* ~800 Hz one-pole for pitch detection */
#define CR_GATE     0.01f
#define CR_ENV_ATK  0.05f
#define CR_ENV_REL  0.0008f
#define CR_MIN_P    40.0f        /* ~1100 Hz */
#define CR_MAX_P    1100.0f      /* ~40 Hz */
#define CR_P_SMOOTH 0.30f
#define CR_MAKEUP   1.8f
#define CR_CLAMP    1.5f

typedef struct CorruptState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    int32_t  sinceCross;

    float lpIn;
    float prevLp;
    float period;
    float mphase;
    float sphase;
    float hphase;
    float tlp;
    float env;
} CorruptState;

/* 1/x via a bit-trick seed + Newton steps (avoids __c6xabi_divf). */
static inline float cr_recip(float x)
{
    union { float f; uint32_t u; } v, y;
    v.f = x;
    y.u = 0x7EF311C3u - v.u;
    y.f = y.f * (2.0f - x * y.f);
    y.f = y.f * (2.0f - x * y.f);
    y.f = y.f * (2.0f - x * y.f);
    return y.f;
}

void CORRUPT_AUDIO_FUNC(unsigned int *ctx)
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
    if (end - base < (uintptr_t)sizeof(CorruptState)) return;

    CorruptState *st = (CorruptState *)base;
    if (st->magic != CR_MAGIC || st->version != CR_VERSION || !st->initialized) {
        st->magic = CR_MAGIC;
        st->version = CR_VERSION;
        st->sinceCross = 0;
        st->lpIn = 0.0f;
        st->prevLp = 0.0f;
        st->period = 200.0f;
        st->mphase = 0.0f;
        st->sphase = 0.0f;
        st->hphase = 0.0f;
        st->tlp = 0.0f;
        st->env = 0.0f;
        st->initialized = 1u;
    }

    float subLvl  = zoom_param_norm01(params[CORRUPT_SUB_SLOT], CORRUPT_SUB_DEFAULT_NORM);
    float tone    = zoom_param_norm01(params[CORRUPT_TONE_SLOT], CORRUPT_TONE_DEFAULT_NORM);
    float waveLvl = zoom_param_norm01(params[CORRUPT_WAVE_SLOT], CORRUPT_WAVE_DEFAULT_NORM);
    float mix     = zoom_param_norm01(params[CORRUPT_MIX_SLOT], CORRUPT_MIX_DEFAULT_NORM);
    float tcoef = 0.04f + tone * 0.6f;      /* output low-pass: dark .. raw */
    float wet = mix;
    float dry = 1.0f - mix;

    float lpIn = st->lpIn, prevLp = st->prevLp, period = st->period;
    float mphase = st->mphase, sphase = st->sphase, hphase = st->hphase;
    float tlp = st->tlp, env = st->env;
    int sinceCross = st->sinceCross;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        float in = 0.5f * (inL + inR);

        float a = in < 0.0f ? -in : in;
        if (a > env) env += CR_ENV_ATK * (a - env);
        else env += CR_ENV_REL * (a - env);

        lpIn += CR_LP_COEF * (in - lpIn);
        sinceCross++;
        if (prevLp < 0.0f && lpIn >= 0.0f && env > CR_GATE) {
            float p = (float)sinceCross;
            if (p >= CR_MIN_P && p <= CR_MAX_P) {
                period += CR_P_SMOOTH * (p - period);
            }
            sinceCross = 0;
        }
        prevLp = lpIn;

        float inc = cr_recip(period);     /* cycles per sample */

        mphase += inc;
        if (mphase >= 1.0f) mphase -= 1.0f;
        float master = mphase < 0.5f ? 1.0f : -1.0f;

        sphase += inc * 0.5f;             /* one octave down */
        if (sphase >= 1.0f) sphase -= 1.0f;
        float sub = sphase < 0.5f ? 1.0f : -1.0f;

        hphase += inc * 2.0f;             /* harmony: one octave up */
        if (hphase >= 1.0f) hphase -= 1.0f;
        float harm = hphase < 0.5f ? 1.0f : -1.0f;

        float synth = env * CR_MAKEUP * (master + subLvl * sub + waveLvl * harm) * 0.45f;
        tlp += tcoef * (synth - tlp);     /* Tone: tames the harsh square edges */
        float o = tlp;
        if (o > CR_CLAMP) o = CR_CLAMP;
        else if (o < -CR_CLAMP) o = -CR_CLAMP;

        fxBuf[f]     = dry * inL + wet * o;
        fxBuf[f + 8] = dry * inR + wet * o;
    }

    st->lpIn = lpIn;
    st->prevLp = prevLp;
    st->period = period;
    st->mphase = mphase;
    st->sphase = sphase;
    st->hphase = hphase;
    st->tlp = tlp;
    st->env = env;
    st->sinceCross = sinceCross;
}
