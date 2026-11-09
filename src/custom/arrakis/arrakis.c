/*
 * arrakis.c -- Arrakis: Dune-style detuned sub-octave drone, MS-70CDR.
 *
 * Pedal port of tools/audio_preview/renderers/arrakis.py. 2 knobs:
 *   Detune (params[5]) - beat spread between the two voices
 *   Mix    (params[6]) - dry/wet
 * Sub-octave depth (-1 oct), sweep rate, drive, and tone are baked.
 *
 * Two granular pitch voices read one octave down from a ctx[3] mono ring,
 * detuned in OPPOSITE directions by a slow polynomial-sine LFO so they beat;
 * voice A -> left, voice B -> right for the wandering stereo throb.
 *
 * Safe-DSP: no math lib (sine is a polynomial approximation; the octave ratio
 * is exactly 0.5; the small detune uses a linear 2^x approximation; the tone
 * filter coefficient is a baked constant). No runtime divide. ctx[3] ring
 * validated + lazily cleared. ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "arrakis_params.h"

#ifndef ARRAKIS_AUDIO_FUNC
#define ARRAKIS_AUDIO_FUNC Fx_MOD_Arrakis
#endif

#define ARRAKIS_DO_PRAGMA(x) _Pragma(#x)
#define ARRAKIS_EXPAND_PRAGMA(x) ARRAKIS_DO_PRAGMA(x)
#define ARRAKIS_CODE_SECTION(f) ARRAKIS_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

ARRAKIS_CODE_SECTION(ARRAKIS_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define ARRAKIS_MAGIC   0x41525241u   /* 'ARRA' */
#define ARRAKIS_VERSION 1u

#define AR_BUF        8192u           /* mono ring (frames) */
#define AR_GRAIN      4096.0f
#define AR_HALF       2048.0f
#define AR_INV_HALF   (1.0f / 2048.0f)
#define AR_CLEAR_STEP 4096u
#define AR_TWO_PI     6.28318530718f
#define AR_LFO_INC    (AR_TWO_PI * 0.15f / 44100.0f)   /* ~0.15 Hz sweep */
#define AR_DRIVE      2.5f
#define AR_LP_A       0.89f           /* ~800 Hz one-pole low-pass */
#define AR_CENTS_MAX  60.0f
#define AR_LN2_1200   (0.69314718f / 1200.0f)

typedef struct ArrakisState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    float pa, pb;
    float lfo;
    float lpA, lpB;
    uint32_t pad;
} ArrakisState;

static inline float ar_abs(float x) { return x < 0.0f ? -x : x; }

static inline float ar_sin(float x)
{
    const float twoPi = 6.28318530718f, pi = 3.14159265359f, inv = 0.15915494309f;
    x = x - twoPi * (float)((int)(x * inv));
    if (x < -pi) x += twoPi;
    if (x > pi) x -= twoPi;
    float y = 1.2732395447f * x - 0.4052847346f * x * ar_abs(x);
    return y + 0.225f * (y * ar_abs(y) - y);
}

static inline float ar_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

/* Linearly interpolated read d frames behind the write head. */
static inline float ar_read(const float *buf, uint32_t wp, float d)
{
    int di = (int)d;
    float fr = d - (float)di;
    int idx = (int)wp - di;
    if (idx < 0) idx += (int)AR_BUF;
    int idxm = idx - 1;
    if (idxm < 0) idxm += (int)AR_BUF;
    return buf[idx] * (1.0f - fr) + buf[idxm] * fr;
}

void ARRAKIS_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(ArrakisState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)AR_BUF * 4u > end) return;

    ArrakisState *st = (ArrakisState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != ARRAKIS_MAGIC || st->version != ARRAKIS_VERSION) {
        st->magic = ARRAKIS_MAGIC;
        st->version = ARRAKIS_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->writePos = 0u;
        st->pa = 0.0f;
        st->pb = AR_HALF;
        st->lfo = 0.0f;
        st->lpA = st->lpB = 0.0f;
    }

    if (!st->initialized) {
        uint32_t e = st->clearIndex + AR_CLEAR_STEP;
        if (e > AR_BUF) e = AR_BUF;
        uint32_t i;
        for (i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= AR_BUF) st->initialized = 1u;
        return;
    }

    float detune = zoom_param_norm01(params[ARRAKIS_DETUNE_SLOT], ARRAKIS_DETUNE_DEFAULT_NORM);
    float mix    = zoom_param_norm01(params[ARRAKIS_MIX_SLOT], ARRAKIS_MIX_DEFAULT_NORM);
    float dAmp = detune * AR_CENTS_MAX * AR_LN2_1200;   /* detune ratio swing */
    float wet = mix;
    float dry = 1.0f - mix;

    uint32_t wp = st->writePos;
    float pa = st->pa, pb = st->pb, lfo = st->lfo, lpA = st->lpA, lpB = st->lpB;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        buf[wp] = 0.5f * (inL + inR);

        lfo += AR_LFO_INC;
        if (lfo > AR_TWO_PI) lfo -= AR_TWO_PI;
        float off = dAmp * ar_sin(lfo);
        float ratioA = 0.5f * (1.0f + off);
        float ratioB = 0.5f * (1.0f - off);

        /* voice A */
        float d1 = pa;
        float d2 = pa + AR_HALF;
        if (d2 >= AR_GRAIN) d2 -= AR_GRAIN;
        float e1 = (AR_HALF - ar_abs(AR_HALF - d1)) * AR_INV_HALF;
        float e2 = (AR_HALF - ar_abs(AR_HALF - d2)) * AR_INV_HALF;
        float vA = ar_read(buf, wp, d1) * e1 + ar_read(buf, wp, d2) * e2;
        pa += (1.0f - ratioA);
        if (pa >= AR_GRAIN) pa -= AR_GRAIN;
        else if (pa < 0.0f) pa += AR_GRAIN;

        /* voice B */
        d1 = pb;
        d2 = pb + AR_HALF;
        if (d2 >= AR_GRAIN) d2 -= AR_GRAIN;
        e1 = (AR_HALF - ar_abs(AR_HALF - d1)) * AR_INV_HALF;
        e2 = (AR_HALF - ar_abs(AR_HALF - d2)) * AR_INV_HALF;
        float vB = ar_read(buf, wp, d1) * e1 + ar_read(buf, wp, d2) * e2;
        pb += (1.0f - ratioB);
        if (pb >= AR_GRAIN) pb -= AR_GRAIN;
        else if (pb < 0.0f) pb += AR_GRAIN;

        float wA = ar_soft(vA * AR_DRIVE);
        float wB = ar_soft(vB * AR_DRIVE);
        lpA = (1.0f - AR_LP_A) * wA + AR_LP_A * lpA;
        lpB = (1.0f - AR_LP_A) * wB + AR_LP_A * lpB;

        fxBuf[f]     = dry * inL + wet * lpA;
        fxBuf[f + 8] = dry * inR + wet * lpB;

        wp++;
        if (wp >= AR_BUF) wp = 0u;
    }

    st->writePos = wp;
    st->pa = pa;
    st->pb = pb;
    st->lfo = lfo;
    st->lpA = lpA;
    st->lpB = lpB;
}
