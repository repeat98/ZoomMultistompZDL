/*
 * mangle.c -- Mangle: a delay whose repeats mutate, MS-70CDR.
 *
 * A feedback delay with three blendable "mangle" characters. Each has its own
 * amount knob and can be dialled in independently (all at 0 = clean delay):
 *   Crush    - sample-rate reduce + bitcrush + darkening, IN the feedback, so
 *              echoes erode more each pass
 *   Tremolo  - amplitude LFO, IN the feedback, so repeats pulse harder as they
 *              regenerate
 *   Pitch    - granular octave-down shimmer on the wet OUTPUT (feed-forward)
 *
 * 6 knobs:
 *   Time     (params[5]) - delay length (~23 ms .. 1.3 s)
 *   Feedback (params[6]) - repeat count / regeneration
 *   Crush    (params[7]) - degradation amount (0 = clean)
 *   Tremolo  (params[8]) - amplitude-wobble depth (0 = off)
 *   Pitch    (params[9]) - octave-down shimmer amount (0 = off)
 *   Mix      (params[10]) - dry/wet
 *
 * SAFE-DSP -- hard-won, see docs/SAFE-DSP-RULES.md:
 *   - NO `switch` anywhere: it compiles to a jump table (a `.switch` section of
 *     code addresses reached by an indirect branch). ZDLs link with zero
 *     relocations, so that branch lands on garbage and the DSP freezes. This
 *     was the real cause of Mangle's long freeze saga. Crush levels are built
 *     with arithmetic instead.
 *   - The granular read is FEED-FORWARD only (never fed back); the feedback
 *     loop carries only the plain-delay signal or scalar-mutated versions of it.
 *   - No math lib, no runtime divide, no static arrays, no float->unsigned cast.
 *   - Denormals flushed so the decaying tail can't stall the FPU.
 *   - ctx[11]/ctx[12] magic shuttle preserved; ctx[3] arena validated + cleared.
 * Verify every build with dis6x: no `.switch:*` section, and no register-
 * indirect branch other than `B B3`.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "mangle_params.h"

#ifndef MANGLE_AUDIO_FUNC
#define MANGLE_AUDIO_FUNC Fx_DLY_Mangle
#endif

#define MANGLE_DO_PRAGMA(x) _Pragma(#x)
#define MANGLE_EXPAND_PRAGMA(x) MANGLE_DO_PRAGMA(x)
#define MANGLE_CODE_SECTION(f) MANGLE_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

MANGLE_CODE_SECTION(MANGLE_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define MG_MAGIC   0x4D414E47u        /* 'MANG' */
#define MG_VERSION 5u                 /* multi-character blendable build */

#define MG_BUF        65536u          /* delay ring, ~1.49 s (power of 2) */
#define MG_MASK       (MG_BUF - 1u)
#define MG_GBUF       8192u           /* small pitch-grain ring (power of 2) */
#define MG_GMASK      (MG_GBUF - 1u)
#define MG_TOTAL      (MG_BUF + MG_GBUF)
#define MG_CLEAR_STEP 4096u
#define MG_DMIN       1024.0f         /* ~23 ms */
#define MG_DMAX       58000.0f        /* ~1.31 s */
#define MG_GRAIN      4096.0f         /* pitch grain length */
#define MG_HALF       2048.0f
#define MG_INV_HALF   (1.0f / 2048.0f)
#define MG_TWO_PI     6.2831853f
#define MG_FB_MAX     0.92f

typedef struct MangleState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    uint32_t gWritePos;               /* pitch-grain ring write head */
    float    grainPhase;              /* pitch grain phase 0..MG_GRAIN */
    float    lfo;                     /* tremolo phase */
    float    shReg;                   /* crush sample-hold register */
    uint32_t shCnt;                   /* crush sample-hold counter */
    float    lpZ;                     /* crush low-pass state */
    uint32_t fpd;                     /* anti-denormal dither (xorshift) */
} MangleState;

static inline float mg_abs(float x) { return x < 0.0f ? -x : x; }

static inline float mg_sin(float x)
{
    const float twoPi = 6.28318530718f, pi = 3.14159265359f, inv = 0.15915494309f;
    x = x - twoPi * (float)((int)(x * inv));
    if (x < -pi) x += twoPi;
    if (x > pi) x -= twoPi;
    float y = 1.2732395447f * x - 0.4052847346f * x * mg_abs(x);
    return y + 0.225f * (y * mg_abs(y) - y);
}

/* unity-slope soft clip: no small-signal gain (safe inside a feedback loop) */
static inline float mg_soft(float x)
{
    if (x > 1.5f) return 1.0f;
    if (x < -1.5f) return -1.0f;
    return x - (x * x * x) * 0.14814815f;   /* x - x^3/6.75 */
}

/* linear read, d samples behind the write head (big delay ring, FIXED d) */
static inline float mg_read(const float *buf, uint32_t wp, float d)
{
    int di = (int)d;
    float fr = d - (float)di;
    uint32_t i0 = (wp - (uint32_t)di) & MG_MASK;
    uint32_t i1 = (i0 - 1u) & MG_MASK;
    return buf[i0] * (1.0f - fr) + buf[i1] * fr;
}

/* linear read on the small grain ring (d stays < MG_GRAIN: small distance) */
static inline float mg_gread(const float *g, uint32_t gwp, float d)
{
    int di = (int)d;
    float fr = d - (float)di;
    uint32_t i0 = (gwp - (uint32_t)di) & MG_GMASK;
    uint32_t i1 = (i0 - 1u) & MG_GMASK;
    return g[i0] * (1.0f - fr) + g[i1] * fr;
}

/* Crush levels as a power of two, WITHOUT a switch (a switch -> jump table ->
 * indirect branch -> freeze here). cMul = 2^bits, cInv = 2^-bits built in the
 * IEEE-754 exponent field (no divide). bits clamped to 3..8. */
static inline void mg_crush_scale(int bits, float *mul, float *inv)
{
    if (bits < 3) bits = 3; else if (bits > 8) bits = 8;
    *mul = (float)(1 << bits);
    union { uint32_t u; float f; } cvt;
    cvt.u = ((uint32_t)(127 - bits)) << 23;   /* exact 2^-bits, mantissa 0 */
    *inv = cvt.f;
}

void MANGLE_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(MangleState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)MG_TOTAL * 4u > end) return;   /* delay ring + grain ring */

    MangleState *st = (MangleState *)base;
    float *buf  = (float *)bufBase;
    float *gbuf = buf + MG_BUF;

    if (st->magic != MG_MAGIC || st->version != MG_VERSION) {
        st->magic = MG_MAGIC;
        st->version = MG_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->writePos = 0u;
        st->gWritePos = 0u;
        st->grainPhase = 0.0f;
        st->lfo = 0.0f;
        st->shReg = 0.0f;
        st->shCnt = 0u;
        st->lpZ = 0.0f;
        st->fpd = 0x2468ACE1u;
    }
    if (st->fpd == 0u) st->fpd = 0x2468ACE1u;   /* never let the dither die */

    if (!st->initialized) {                     /* clear both rings, one chunk per call */
        uint32_t e = st->clearIndex + MG_CLEAR_STEP;
        if (e > MG_TOTAL) e = MG_TOTAL;
        uint32_t i;
        for (i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= MG_TOTAL) st->initialized = 1u;
        return;
    }

    float time  = zoom_param_norm01(params[MANGLE_TIME_SLOT], MANGLE_TIME_DEFAULT_NORM);
    float fbk   = zoom_param_norm01(params[MANGLE_FEEDBK_SLOT], MANGLE_FEEDBK_DEFAULT_NORM);
    float crush = zoom_param_norm01(params[MANGLE_CRUSH_SLOT], MANGLE_CRUSH_DEFAULT_NORM);
    float trmA  = zoom_param_norm01(params[MANGLE_TREMOLO_SLOT], MANGLE_TREMOLO_DEFAULT_NORM);
    float ptchA = zoom_param_norm01(params[MANGLE_PITCH_SLOT], MANGLE_PITCH_DEFAULT_NORM);
    float mix   = zoom_param_norm01(params[MANGLE_MIX_SLOT], MANGLE_MIX_DEFAULT_NORM);

    float delay = MG_DMIN + time * (MG_DMAX - MG_DMIN);
    float fb = fbk * MG_FB_MAX;
    float wet = mix, dry = 1.0f - mix;

    /* Crush -> sample-rate reduction (hold 1..12) + bit depth (8..3) + tone. */
    uint32_t shN = 1u + (uint32_t)(int)(crush * 11.0f);   /* signed int cast: no __c6xabi_fixfu */
    int bits = 8 - (int)(crush * 5.0f);
    float cMul = 256.0f, cInv = 0.00390625f;
    mg_crush_scale(bits, &cMul, &cInv);
    float lpCoef = 0.95f - 0.85f * crush;                 /* more crush = darker feedback */

    /* Tremolo -> depth + a fixed ~4.5 Hz rate. */
    float lfoInc = 4.5f * (MG_TWO_PI / 44100.0f);

    /* Pitch -> octave-down grain ratio + a blend amount so the grain fades out
     * cleanly at 0 (no comb colouration when pitch is off). */
    float ratio = 1.0f - 0.5f * ptchA;                    /* 1.0 .. 0.5 (oct down) */
    float gInc = 1.0f - ratio;

    uint32_t wp = st->writePos, gwp = st->gWritePos, shCnt = st->shCnt, fpd = st->fpd;
    float gph = st->grainPhase, lfo = st->lfo, shReg = st->shReg, lpZ = st->lpZ;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        float in = 0.5f * (inL + inR);

        /* delay tap: ONE fixed-distance read (the only pattern proven safe) */
        float tap = mg_read(buf, wp, delay);

        /* --- feedback-side mangling (compounds every pass), all scalar --- */
        /* tremolo */
        float trem = 1.0f - trmA * (0.5f - 0.5f * mg_sin(lfo));
        lfo += lfoInc;
        if (lfo > MG_TWO_PI) lfo -= MG_TWO_PI;
        float t = tap * trem;

        /* crush: sample-hold -> quantise -> darken -> soft-clip, blended in */
        shCnt++;
        if (shCnt >= shN) { shReg = t; shCnt = 0u; }
        float q = (float)((int)(shReg * cMul + (shReg >= 0.0f ? 0.5f : -0.5f))) * cInv;
        lpZ += lpCoef * (q - lpZ);
        if (lpZ > -1.0e-25f && lpZ < 1.0e-25f) lpZ = 0.0f;   /* flush low-pass denormals */
        float crushed = mg_soft(lpZ * 1.15f);
        float proc = t + crush * (crushed - t);              /* blend clean <-> crushed */

        /* feedback ring write (smoke-proven plain-delay loop) */
        float v = in + fb * proc;
        if (v > -1.18e-23f && v < 1.18e-23f) v = (float)fpd * 1.18e-17f;
        fpd ^= fpd << 13; fpd ^= fpd >> 17; fpd ^= fpd << 5;
        buf[wp] = mg_soft(v);

        /* --- pitch shimmer on the OUTPUT (feed-forward grain, Arrakis-safe) --- */
        gbuf[gwp] = proc;
        float g2 = gph + MG_HALF;
        if (g2 >= MG_GRAIN) g2 -= MG_GRAIN;
        float e1 = (MG_HALF - mg_abs(MG_HALF - gph)) * MG_INV_HALF;
        float e2 = (MG_HALF - mg_abs(MG_HALF - g2)) * MG_INV_HALF;
        float pitched = mg_gread(gbuf, gwp, gph) * e1 + mg_gread(gbuf, gwp, g2) * e2;
        gph += gInc;
        if (gph >= MG_GRAIN) gph -= MG_GRAIN;
        else if (gph < 0.0f) gph += MG_GRAIN;
        gwp = (gwp + 1u) & MG_GMASK;

        float wetSig = proc + ptchA * (pitched - proc);      /* blend dry <-> pitched */

        fxBuf[f]     = dry * inL + wet * wetSig;
        fxBuf[f + 8] = dry * inR + wet * wetSig;

        wp = (wp + 1u) & MG_MASK;
    }

    st->writePos = wp;
    st->gWritePos = gwp;
    st->grainPhase = gph;
    st->lfo = lfo;
    st->shReg = shReg;
    st->shCnt = shCnt;
    st->lpZ = lpZ;
    st->fpd = fpd;
}
