/*
 * genloss.c -- GenLoss: tape/VHS generation-loss degradation, MS-70CDR.
 *
 * Pedal port (v1) of tools/audio_preview/renderers/genloss.py. Chain:
 *   saturation -> wow & flutter (modulated fractional delay) -> sub high-pass
 *   -> Tone low-pass -> + hiss.
 * Random dropouts from the desktop version are deferred (the filtered random
 * walk still gives unstable-tape warble). 2 knobs:
 *   Wow  (params[5]) - wow & flutter + pitch-instability depth
 *   Tone (params[6]) - bandwidth / brightness (low-pass cutoff)
 * Drive, hiss, and mix are baked.
 *
 * Safe-DSP: no math lib (polynomial sine LFOs, cubic soft-clip, one-pole
 * filters with baked/linear coefficients, xorshift noise), no runtime divide,
 * no modulo. A small mono delay ring lives in the ctx[3] arena (cleared once
 * at init). ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "genloss_params.h"

#ifndef GENLOSS_AUDIO_FUNC
#define GENLOSS_AUDIO_FUNC Fx_MOD_GenLoss
#endif

#define GENLOSS_DO_PRAGMA(x) _Pragma(#x)
#define GENLOSS_EXPAND_PRAGMA(x) GENLOSS_DO_PRAGMA(x)
#define GENLOSS_CODE_SECTION(f) GENLOSS_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

GENLOSS_CODE_SECTION(GENLOSS_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define GL_MAGIC   0x474C5353u   /* 'GLSS' */
#define GL_VERSION 1u

#define GL_BUF        2048u
#define GL_TWO_PI     6.28318530718f
#define GL_WOW_INC    (GL_TWO_PI * 0.7f / 44100.0f)
#define GL_FLUT_INC   (GL_TWO_PI * 8.0f / 44100.0f)
#define GL_BASE       529.0f      /* ~12 ms base delay */
#define GL_WOW_AMP    176.0f      /* ~4 ms wow at full Wow */
#define GL_FLUT_AMP   40.0f
#define GL_RW_AMP     120.0f
#define GL_RW_COEF    0.0012f
#define GL_HP_COEF    0.012f      /* sub high-pass (~80 Hz) */
/* By-ear level match: the tape path is driven and band-limited, so it needs a
 * small trim before being crossfaded against dry. */
#define GL_WET_TRIM   1.15f
#define GL_DRIVE      1.8f
#define GL_HISS       0.006f

typedef struct GenLossState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t writePos;
    float wowPhase, flutPhase, rwLP, hp, lp;
    uint32_t rng;
    uint32_t pad;
} GenLossState;

static inline float gl_abs(float x) { return x < 0.0f ? -x : x; }

static inline float gl_sin(float x)
{
    const float twoPi = 6.28318530718f, pi = 3.14159265359f, inv = 0.15915494309f;
    x = x - twoPi * (float)((int)(x * inv));
    if (x < -pi) x += twoPi;
    if (x > pi) x -= twoPi;
    float y = 1.2732395447f * x - 0.4052847346f * x * gl_abs(x);
    return y + 0.225f * (y * gl_abs(y) - y);
}

static inline float gl_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

static inline uint32_t gl_xs(uint32_t *s)
{
    uint32_t x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

static inline float gl_rand(uint32_t *s)
{
    uint32_t u = gl_xs(s) >> 9;
    return (float)(int)u * (1.0f / 8388608.0f) * 2.0f - 1.0f;   /* [-1,1) */
}

static inline float gl_read(const float *buf, uint32_t wp, float delay)
{
    int di = (int)delay;
    float fr = delay - (float)di;
    int idx = (int)wp - di;
    if (idx < 0) idx += (int)GL_BUF;
    int idxm = idx - 1;
    if (idxm < 0) idxm += (int)GL_BUF;
    return buf[idx] * (1.0f - fr) + buf[idxm] * fr;
}

void GENLOSS_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(GenLossState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)GL_BUF * 4u > end) return;

    GenLossState *st = (GenLossState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != GL_MAGIC || st->version != GL_VERSION || !st->initialized) {
        st->magic = GL_MAGIC;
        st->version = GL_VERSION;
        st->writePos = 0u;
        st->wowPhase = st->flutPhase = 0.0f;
        st->rwLP = st->hp = st->lp = 0.0f;
        st->rng = 0x1F123BB5u;
        uint32_t i;
        for (i = 0u; i < GL_BUF; i++) buf[i] = 0.0f;
        st->initialized = 1u;
    }

    float wow  = zoom_param_norm01(params[GENLOSS_WOW_SLOT], GENLOSS_WOW_DEFAULT_NORM);
    float tone = zoom_param_norm01(params[GENLOSS_TONE_SLOT], GENLOSS_TONE_DEFAULT_NORM);
    float hiss = zoom_param_norm01(params[GENLOSS_HISS_SLOT], GENLOSS_HISS_DEFAULT_NORM);
    float lpCoef = 0.03f + tone * 0.5f;     /* one-pole cutoff ~210 Hz .. ~3.7 kHz */
    float hissLvl = hiss * 0.03f;           /* 0 .. ~0.03 noise floor */
    /* Dry/wet crossfade. Every other effect in the pack ends with one; GenLoss
     * shipped with none, so it could only ever be heard fully wet. */
    float mix = zoom_param_norm01(params[GENLOSS_MIX_SLOT], GENLOSS_MIX_DEFAULT_NORM);
    float wetLvl = mix;
    float dryLvl = 1.0f - mix;

    uint32_t wp = st->writePos;
    float wowPh = st->wowPhase, flutPh = st->flutPhase, rwLP = st->rwLP;
    float hp = st->hp, lp = st->lp;
    uint32_t rng = st->rng;

    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];
        float in = 0.5f * (inL + inR);

        float s = gl_soft(in * GL_DRIVE);
        buf[wp] = s;

        wowPh += GL_WOW_INC;
        if (wowPh > GL_TWO_PI) wowPh -= GL_TWO_PI;
        flutPh += GL_FLUT_INC;
        if (flutPh > GL_TWO_PI) flutPh -= GL_TWO_PI;
        rwLP += GL_RW_COEF * (gl_rand(&rng) - rwLP);

        float mod = GL_BASE
                  + wow * GL_WOW_AMP * gl_sin(wowPh)
                  + wow * GL_FLUT_AMP * gl_sin(flutPh)
                  + wow * GL_RW_AMP * rwLP;
        float warb = gl_read(buf, wp, mod);

        hp += GL_HP_COEF * (warb - hp);
        float wh = warb - hp;            /* high-passed */
        lp += lpCoef * (wh - lp);        /* low-passed (Tone) */
        float wet = lp + gl_rand(&rng) * hissLvl;
        float out = dryLvl * in + wetLvl * wet * GL_WET_TRIM;

        fxBuf[i]     = out;
        fxBuf[i + 8] = out;

        wp++;
        if (wp >= GL_BUF) wp = 0u;
    }

    st->writePos = wp;
    st->wowPhase = wowPh;
    st->flutPhase = flutPh;
    st->rwLP = rwLP;
    st->hp = hp;
    st->lp = lp;
    st->rng = rng;
}
