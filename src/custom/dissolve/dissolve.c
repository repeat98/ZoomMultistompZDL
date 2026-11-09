/*
 * dissolve.c -- Dissolve: OBNE Parting-style glitch delay, MS-70CDR.
 *
 * A ~400 ms delay line whose INPUT is randomly gated in ~46 ms chunks, whose
 * FEEDBACK runs through allpass diffusion (so repeats smear toward reverb
 * wash), and whose READ head randomly plays chunks reversed or at half speed
 * (octave down). 4 knobs:
 *   Chance (params[5]) - probability an input chunk is dropped before the
 *                        delay line (stutter/erosion at the entry).
 *   Smear  (params[6]) - feedback amount + diffusion: slapback .. washy
 *                        near-reverb dissolve.
 *   Glitch (params[7]) - probability a read chunk plays reversed or an
 *                        octave down.
 *   Mix    (params[8]) - dry/wet.
 *
 * Safe-DSP: no math lib, no runtime divide, no static arrays (allpass
 * lengths are #define'd struct buffers). Soft-clipped feedback keeps the
 * loop bounded even at max Smear. Mono line in the ctx[3] arena (validated,
 * lazily cleared). ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "dissolve_params.h"

#ifndef DISSOLVE_AUDIO_FUNC
#define DISSOLVE_AUDIO_FUNC Fx_DLY_Dissolve
#endif

#define DISSOLVE_DO_PRAGMA(x) _Pragma(#x)
#define DISSOLVE_EXPAND_PRAGMA(x) DISSOLVE_DO_PRAGMA(x)
#define DISSOLVE_CODE_SECTION(f) DISSOLVE_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

DISSOLVE_CODE_SECTION(DISSOLVE_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define DISSOLVE_MAGIC   0x44495356u   /* 'DISV' */
#define DISSOLVE_VERSION 1u

#define DS_BUF        32768u           /* mono delay ring (power of 2) */
#define DS_MASK       (DS_BUF - 1u)
#define DS_CLEAR_STEP 4096u
#define DS_DELAY      17640u           /* ~400 ms tap */
#define DS_TAP_R      17070u           /* R tap slightly early -> width */
#define DS_CHUNK      2048u            /* glitch/gate decision chunk (~46 ms) */
#define DS_AP1        331u             /* diffusion allpass lengths (co-prime) */
#define DS_AP2        743u
#define DS_FB_MIN     0.30f
#define DS_FB_SPAN    0.62f            /* Smear=1 -> fb 0.92 (soft-clipped) */
#define DS_DAMP       0.30f            /* feedback high damping */

typedef struct DissolveState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    uint32_t chunkPos;
    uint32_t gateOn;                   /* this chunk feeds the line? */
    uint32_t readMode;                 /* 0 normal, 1 reverse, 2 half-rate */
    float readOff;                     /* within-chunk read offset */
    float lpFb;                        /* feedback damping state */
    uint32_t ai1;
    uint32_t ai2;
    uint32_t rng;

    float ap1[DS_AP1];
    float ap2[DS_AP2];
    float line[DS_BUF];
} DissolveState;

/* Unity-gain soft clip: slope 1 at zero (a small-signal boost here would
 * multiply into the feedback loop gain and self-oscillate at max Smear),
 * compressing smoothly to +/-1.0 at +/-1.5. */
static inline float ds_soft(float x)
{
    if (x > 1.5f) return 1.0f;
    if (x < -1.5f) return -1.0f;
    return x - (x * x * x) * 0.14814815f;   /* x - x^3/6.75 */
}

static inline uint32_t ds_rng(uint32_t r)
{
    r ^= r << 13;
    r ^= r >> 17;
    r ^= r << 5;
    return r;
}

#define DS_RAND01(r) ((float)((r) >> 8) * 5.9604645e-8f)

static inline float ds_read(const float *line, uint32_t wp, float d)
{
    int di = (int)d;
    float fr = d - (float)di;
    uint32_t idx0 = (wp - (uint32_t)di) & DS_MASK;
    uint32_t idx1 = (idx0 - 1u) & DS_MASK;
    return line[idx0] * (1.0f - fr) + line[idx1] * fr;
}

void DISSOLVE_AUDIO_FUNC(unsigned int *ctx)
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
    if (end - base < (uintptr_t)sizeof(DissolveState)) return;

    DissolveState *st = (DissolveState *)base;

    if (st->magic != DISSOLVE_MAGIC || st->version != DISSOLVE_VERSION) {
        st->magic = DISSOLVE_MAGIC;
        st->version = DISSOLVE_VERSION;
        st->initialized = 0u;
        st->clearIndex = 16u;
    }

    if (!st->initialized) {
        /* chunked clear of the whole struct (buffers included) */
        uint32_t *w = (uint32_t *)(void *)st;
        uint32_t startWord = st->clearIndex >> 2;
        uint32_t endWord = startWord + (DS_CLEAR_STEP >> 2);
        uint32_t totalWords = (uint32_t)(sizeof(DissolveState) >> 2);
        uint32_t i;
        if (endWord > totalWords) endWord = totalWords;
        for (i = startWord; i < endWord; i++) w[i] = 0u;
        st->clearIndex = endWord << 2;
        if (endWord >= totalWords) {
            st->writePos = 0u;
            st->chunkPos = 0u;
            st->gateOn = 1u;
            st->readMode = 0u;
            st->readOff = 0.0f;
            st->lpFb = 0.0f;
            st->ai1 = 0u;
            st->ai2 = 0u;
            st->rng = 0x89ABCDFu;
            st->initialized = 1u;
        }
        return;
    }

    float chance = zoom_param_norm01(params[DISSOLVE_CHANCE_SLOT], DISSOLVE_CHANCE_DEFAULT_NORM);
    float smear  = zoom_param_norm01(params[DISSOLVE_SMEAR_SLOT], DISSOLVE_SMEAR_DEFAULT_NORM);
    float glitch = zoom_param_norm01(params[DISSOLVE_GLITCH_SLOT], DISSOLVE_GLITCH_DEFAULT_NORM);
    float mix    = zoom_param_norm01(params[DISSOLVE_MIX_SLOT], DISSOLVE_MIX_DEFAULT_NORM);

    float fb = DS_FB_MIN + smear * DS_FB_SPAN;
    float apg = 0.20f + smear * 0.45f;         /* diffusion strength */
    float wet = mix;
    float dry = 1.0f - mix;

    uint32_t wp = st->writePos, cp = st->chunkPos;
    uint32_t gate = st->gateOn, mode = st->readMode;
    float roff = st->readOff, lpFb = st->lpFb;
    uint32_t a1 = st->ai1, a2 = st->ai2, rng = st->rng;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        float in = 0.5f * (inL + inR);

        /* per-chunk decisions: input gate + read mode */
        if (cp == 0u) {
            rng = ds_rng(rng);
            gate = (DS_RAND01(rng) < chance * 0.9f) ? 0u : 1u;
            rng = ds_rng(rng);
            if (DS_RAND01(rng) < glitch * 0.85f) {
                rng = ds_rng(rng);
                mode = ((rng >> 6) & 1u) ? 1u : 2u;   /* reverse : half-rate */
            } else {
                mode = 0u;
            }
            roff = 0.0f;
        }

        /* read head: normal tap, reversed chunk, or half-rate chunk */
        float dL, dR;
        if (mode == 1u) {              /* reverse inside the chunk window */
            float back = (float)DS_CHUNK - roff;
            dL = (float)DS_DELAY + back;
            dR = (float)DS_TAP_R + back;
            roff += 2.0f;              /* reverse relative to moving write head */
            if (roff > (float)DS_CHUNK) roff = (float)DS_CHUNK;
        } else if (mode == 2u) {       /* half-rate: octave down */
            dL = (float)DS_DELAY + roff;
            dR = (float)DS_TAP_R + roff;
            roff += 0.5f;              /* falls behind the write head at 1/2x */
        } else {
            dL = (float)DS_DELAY;
            dR = (float)DS_TAP_R;
        }

        float outL = ds_read(st->line, wp, dL);
        float outR = ds_read(st->line, wp, dR);
        float mono = 0.5f * (outL + outR);

        /* feedback: damp -> diffuse (2 allpasses) -> soft clip -> line */
        lpFb += DS_DAMP * (mono - lpFb);
        float x = lpFb;
        float d1 = st->ap1[a1];
        float y1 = -apg * x + d1;
        st->ap1[a1] = x + apg * y1;
        a1++; if (a1 >= DS_AP1) a1 = 0u;
        float d2 = st->ap2[a2];
        float y2 = -apg * y1 + d2;
        st->ap2[a2] = y1 + apg * y2;
        a2++; if (a2 >= DS_AP2) a2 = 0u;

        st->line[wp] = ds_soft((gate ? in : 0.0f) + y2 * fb);

        fxBuf[f]     = dry * inL + wet * outL;
        fxBuf[f + 8] = dry * inR + wet * outR;

        wp = (wp + 1u) & DS_MASK;
        cp++;
        if (cp >= DS_CHUNK) cp = 0u;
    }

    st->writePos = wp;
    st->chunkPos = cp;
    st->gateOn = gate;
    st->readMode = mode;
    st->readOff = roff;
    st->lpFb = lpFb;
    st->ai1 = a1;
    st->ai2 = a2;
    st->rng = rng;
}
