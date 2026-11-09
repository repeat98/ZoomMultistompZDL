/*
 * microloom.c -- Microloom: granular shimmer cloud, MS-70CDR.
 *
 * Pedal port (v1) of tools/audio_preview/renderers/microloom.py, reduced to
 * the sustaining-shimmer core that fits the pedal runtime: a +1 octave
 * pitch-shifted feedback delay with allpass diffusion. The separate reverb
 * tank from the desktop version is dropped for now (CPU/memory). 2 knobs:
 *   Regen (params[5]) - feedback / cloud length
 *   Mix   (params[6]) - dry/wet
 * Octave, grain size, base delay, and shimmer amount are baked.
 *
 * Safe-DSP: no math lib (octave ratio is exactly 2.0; envelopes are linear;
 * filter coefficients are baked constants), no runtime divide, no modulo.
 * A mono delay ring + three allpass buffers live contiguously in the ctx[3]
 * arena, validated + lazily cleared. ctx[11]/ctx[12] magic shuttle preserved.
 * Feedback is clamped so the loop cannot blow up.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "microloom_params.h"

#ifndef MICROLOOM_AUDIO_FUNC
#define MICROLOOM_AUDIO_FUNC Fx_DLY_Microlm
#endif

#define MICROLOOM_DO_PRAGMA(x) _Pragma(#x)
#define MICROLOOM_EXPAND_PRAGMA(x) MICROLOOM_DO_PRAGMA(x)
#define MICROLOOM_CODE_SECTION(f) MICROLOOM_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

MICROLOOM_CODE_SECTION(MICROLOOM_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define ML_MAGIC   0x4D4C4F4Fu   /* 'MLOO' */
#define ML_VERSION 2u

#define ML_MB        24576u      /* main delay ring (frames) */
#define ML_AP0       113u
#define ML_AP1       337u
#define ML_AP2       671u
#define ML_REGION    (ML_MB + ML_AP0 + ML_AP1 + ML_AP2)
#define ML_CLEAR_STEP 4096u

#define ML_GRAIN     6000.0f
#define ML_HALF      3000.0f
#define ML_INV_HALF  (1.0f / 3000.0f)
#define ML_BASE      7764.0f     /* base feedback delay (frames) */
#define ML_SHIMMER   0.45f       /* pitched injection level */
#define ML_AP_G      0.6f
#define ML_LP_COEF   0.0008f     /* feedback low-cut */
#define ML_CLAMP     3.0f

typedef struct MicroloomState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    float phase;
    float feed;
    float lp;
    float olp;
    uint32_t ap0i, ap1i, ap2i;
    uint32_t pad;
} MicroloomState;

static inline float ml_read(const float *buf, uint32_t wp, float delay)
{
    int di = (int)delay;
    float fr = delay - (float)di;
    int idx = (int)wp - di;
    if (idx < 0) idx += (int)ML_MB;
    int idxm = idx - 1;
    if (idxm < 0) idxm += (int)ML_MB;
    return buf[idx] * (1.0f - fr) + buf[idxm] * fr;
}

void MICROLOOM_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t regionBase = (base + sizeof(MicroloomState) + 7u) & ~(uintptr_t)7u;
    if (regionBase + (uintptr_t)ML_REGION * 4u > end) return;

    MicroloomState *st = (MicroloomState *)base;
    float *buf  = (float *)regionBase;
    float *ap0  = buf + ML_MB;
    float *ap1  = ap0 + ML_AP0;
    float *ap2  = ap1 + ML_AP1;

    if (st->magic != ML_MAGIC || st->version != ML_VERSION) {
        st->magic = ML_MAGIC;
        st->version = ML_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->writePos = 0u;
        st->phase = 0.0f;
        st->feed = 0.0f;
        st->lp = 0.0f;
        st->olp = 0.0f;
        st->ap0i = st->ap1i = st->ap2i = 0u;
    }

    if (!st->initialized) {
        uint32_t e = st->clearIndex + ML_CLEAR_STEP;
        if (e > ML_REGION) e = ML_REGION;
        uint32_t i;
        for (i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= ML_REGION) st->initialized = 1u;
        return;
    }

    float pitch = zoom_param_norm01(params[MICROLOOM_PITCH_SLOT], MICROLOOM_PITCH_DEFAULT_NORM);
    float regen = zoom_param_norm01(params[MICROLOOM_REGEN_SLOT], MICROLOOM_REGEN_DEFAULT_NORM);
    float tone  = zoom_param_norm01(params[MICROLOOM_TONE_SLOT], MICROLOOM_TONE_DEFAULT_NORM);
    float mix   = zoom_param_norm01(params[MICROLOOM_MIX_SLOT], MICROLOOM_MIX_DEFAULT_NORM);
    float ratio = 0.5f + pitch * 1.5f;       /* 0.5 (oct down) .. 2.0 (oct up) */
    float tcoef = 0.05f + tone * 0.7f;       /* output low-pass: dark .. bright */
    float regenGain = regen * 0.85f;
    /* Loop-gain cap: near unison pitch the shimmer tap correlates with the
     * clean tap, so total loop gain is regenGain + shimmer. Keep that sum
     * below 1 or the cloud grows until it pins at ML_CLAMP and never decays. */
    float shimmer = 0.98f - regenGain;
    if (shimmer > ML_SHIMMER) shimmer = ML_SHIMMER;
    float wet = mix;
    float dry = 1.0f - mix;

    uint32_t wp = st->writePos;
    float phase = st->phase, feed = st->feed, lp = st->lp, olp = st->olp;
    uint32_t a0 = st->ap0i, a1 = st->ap1i, a2 = st->ap2i;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        float in = 0.5f * (inL + inR);
        buf[wp] = in + feed;

        float clean = ml_read(buf, wp, ML_BASE);

        float d1 = phase;
        float d2 = phase + ML_HALF;
        if (d2 >= ML_GRAIN) d2 -= ML_GRAIN;
        float e1 = (ML_HALF - (d1 < ML_HALF ? ML_HALF - d1 : d1 - ML_HALF)) * ML_INV_HALF;
        float e2 = (ML_HALF - (d2 < ML_HALF ? ML_HALF - d2 : d2 - ML_HALF)) * ML_INV_HALF;
        float pitched = ml_read(buf, wp, ML_BASE + d1) * e1 + ml_read(buf, wp, ML_BASE + d2) * e2;
        phase += (1.0f - ratio);             /* Pitch knob sets shift ratio */
        if (phase < 0.0f) phase += ML_GRAIN;
        else if (phase >= ML_GRAIN) phase -= ML_GRAIN;

        float x = regenGain * clean + shimmer * pitched;

        /* allpass diffusion chain */
        float d, y;
        d = ap0[a0]; y = -ML_AP_G * x + d; ap0[a0] = x + ML_AP_G * y; a0++; if (a0 >= ML_AP0) a0 = 0u; x = y;
        d = ap1[a1]; y = -ML_AP_G * x + d; ap1[a1] = x + ML_AP_G * y; a1++; if (a1 >= ML_AP1) a1 = 0u; x = y;
        d = ap2[a2]; y = -ML_AP_G * x + d; ap2[a2] = x + ML_AP_G * y; a2++; if (a2 >= ML_AP2) a2 = 0u; x = y;

        lp += ML_LP_COEF * (x - lp);
        feed = x - lp;
        if (feed > ML_CLAMP) feed = ML_CLAMP;
        else if (feed < -ML_CLAMP) feed = -ML_CLAMP;

        olp += tcoef * (feed - olp);         /* Tone: output low-pass */
        fxBuf[f]     = dry * inL + wet * olp;
        fxBuf[f + 8] = dry * inR + wet * olp;

        wp++;
        if (wp >= ML_MB) wp = 0u;
    }

    st->writePos = wp;
    st->phase = phase;
    st->feed = feed;
    st->lp = lp;
    st->olp = olp;
    st->ap0i = a0;
    st->ap1i = a1;
    st->ap2i = a2;
}
