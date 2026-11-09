/*
 * shatter.c -- Shatter: stutter / beat-repeat glitch for the Zoom MS-70CDR.
 *
 * Pedal port of tools/audio_preview/renderers/shatter.py. 2 knobs:
 *   Chance (params[5]) - probability each slice is glitched
 *   Mix    (params[6]) - dry/wet
 * Slice length, stutter subdivision, and reverse probability are baked.
 * (Bitcrush from the desktop version is deferred to a later increment.)
 *
 * Safe-DSP: no math lib, no runtime divide, no modulo (counters wrap by
 * compare). A stereo capture ring lives in the host ctx[3] arena, validated
 * before use and lazily zeroed in chunks (bulk-clearing it in one audio call
 * could overrun). ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "shatter_params.h"

#ifndef SHATTER_AUDIO_FUNC
#define SHATTER_AUDIO_FUNC Fx_DLY_Shatter
#endif

#define SHATTER_DO_PRAGMA(x) _Pragma(#x)
#define SHATTER_EXPAND_PRAGMA(x) SHATTER_DO_PRAGMA(x)
#define SHATTER_CODE_SECTION(f) SHATTER_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

SHATTER_CODE_SECTION(SHATTER_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define SHATTER_MAGIC   0x53484154u   /* 'SHAT' */
#define SHATTER_VERSION 1u

#define SH_BUFLEN       22050u        /* 0.5 s stereo capture ring (frames) */
#define SH_SLICE        8192u         /* ~186 ms glitch slice */
#define SH_SUB          1366u         /* stutter sub-slice (~SLICE/6) */
#define SH_CLEAR_STEP   4096u
#define SH_TOTAL_FLOATS (2u * SH_BUFLEN)
#define SH_REV_THRESH   19660u        /* ~30% of glitches reverse */

typedef struct ShatterState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    int32_t  sliceCount;
    int32_t  mode;        /* 0 dry, 1 stutter, 2 reverse */
    uint32_t srcStart;    /* start frame of the previous (recorded) slice */
    int32_t  subPos;
    int32_t  revPos;
    uint32_t rng;
    uint32_t pad;
} ShatterState;

static inline uint32_t sh_xs(uint32_t *s)
{
    uint32_t x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

void SHATTER_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(ShatterState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)SH_TOTAL_FLOATS * 4u > end) return;

    ShatterState *st = (ShatterState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != SHATTER_MAGIC || st->version != SHATTER_VERSION) {
        st->magic = SHATTER_MAGIC;
        st->version = SHATTER_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->writePos = 0u;
        st->sliceCount = 0;
        st->mode = 0;
        st->srcStart = 0u;
        st->subPos = 0;
        st->revPos = 0;
        st->rng = 0x6D2B79F5u;
    }

    if (!st->initialized) {
        uint32_t e = st->clearIndex + SH_CLEAR_STEP;
        if (e > SH_TOTAL_FLOATS) e = SH_TOTAL_FLOATS;
        uint32_t i;
        for (i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= SH_TOTAL_FLOATS) st->initialized = 1u;
        return;                       /* pass dry while clearing */
    }

    float chance = zoom_param_norm01(params[SHATTER_CHANCE_SLOT], SHATTER_CHANCE_DEFAULT_NORM);
    float mix    = zoom_param_norm01(params[SHATTER_MIX_SLOT], SHATTER_MIX_DEFAULT_NORM);
    int chanceThr = (int)(chance * 65536.0f);
    float wet = mix;
    float dry = 1.0f - mix;

    uint32_t wp = st->writePos;
    int sc = st->sliceCount;
    int mode = st->mode;
    uint32_t src = st->srcStart;
    int subPos = st->subPos;
    int revPos = st->revPos;
    uint32_t rng = st->rng;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        buf[2u * wp] = inL;
        buf[2u * wp + 1u] = inR;

        if (sc <= 0) {
            sc = (int)SH_SLICE;
            uint32_t r = sh_xs(&rng);
            if ((int)(r & 0xFFFFu) < chanceThr) {
                mode = (((r >> 16) & 0xFFFFu) < SH_REV_THRESH) ? 2 : 1;
                src = (wp >= SH_SLICE) ? (wp - SH_SLICE) : (wp + SH_BUFLEN - SH_SLICE);
                subPos = 0;
                revPos = 0;
            } else {
                mode = 0;
            }
        }
        sc--;

        float oL, oR;
        if (mode == 1) {
            uint32_t fr = src + (uint32_t)subPos;
            if (fr >= SH_BUFLEN) fr -= SH_BUFLEN;
            oL = buf[2u * fr];
            oR = buf[2u * fr + 1u];
            subPos++;
            if (subPos >= (int)SH_SUB) subPos = 0;
        } else if (mode == 2) {
            uint32_t fr = src + (SH_SLICE - 1u - (uint32_t)revPos);
            if (fr >= SH_BUFLEN) fr -= SH_BUFLEN;
            oL = buf[2u * fr];
            oR = buf[2u * fr + 1u];
            revPos++;
            if (revPos >= (int)SH_SLICE) revPos = 0;
        } else {
            oL = inL;
            oR = inR;
        }

        fxBuf[f]     = dry * inL + wet * oL;
        fxBuf[f + 8] = dry * inR + wet * oR;

        wp++;
        if (wp >= SH_BUFLEN) wp = 0u;
    }

    st->writePos = wp;
    st->sliceCount = sc;
    st->mode = mode;
    st->srcStart = src;
    st->subPos = subPos;
    st->revPos = revPos;
    st->rng = rng;
}
