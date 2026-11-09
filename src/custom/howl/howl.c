/*
 * howl.c -- Howl: feedback/resonant "howl" effect, MS-70CDR.
 *
 * v2 rewrite. The v1 design fed a resonant SVF back on itself; its loop gain
 * (fbgain x the filter's resonance peak) crossed unity at almost any setting,
 * so it self-oscillated into CONSTANT NOISE on hardware. This version uses a
 * tuned 2-pole resonator with a controllable pole radius r < 1: the radius is
 * ALWAYS below 1, so it is unconditionally stable and decays to silence when
 * you stop playing (no constant noise), while r near 1 gives a multi-second
 * feedback howl. Your input excites it; the grit (soft-clip) sits OUTSIDE the
 * loop so it can never destabilize.
 *
 * 2 knobs:
 *   Tune    (params[5]) - resonant frequency (80..1950 Hz)
 *   Annihil (params[6]) - pole radius / howl length (short ring -> long howl)
 *
 * Safe-DSP: no math lib (cos via small-angle 1 - w^2/2, valid since the Tune
 * range keeps w < 0.28; cubic soft-clip), no runtime divide, no buffer. Tiny
 * ctx[3] state. ctx[11]/ctx[12] magic shuttle preserved. Pole radius capped
 * below 1 -> cannot run away.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "howl_params.h"

#ifndef HOWL_AUDIO_FUNC
#define HOWL_AUDIO_FUNC Fx_DYN_Howl
#endif

#define HOWL_DO_PRAGMA(x) _Pragma(#x)
#define HOWL_EXPAND_PRAGMA(x) HOWL_DO_PRAGMA(x)
#define HOWL_CODE_SECTION(f) HOWL_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

HOWL_CODE_SECTION(HOWL_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define HOWL_MAGIC   0x484F574Cu   /* 'HOWL' */
#define HOWL_VERSION 3u

#define HOWL_TWO_PI_SR (6.2831853f / 44100.0f)
#define HOWL_FC_MIN    80.0f
#define HOWL_FC_SPAN   1870.0f
#define HOWL_GAP_MIN   3.0e-5f      /* (1-r) at max Annihil -> longest howl */
#define HOWL_GAP_MAX   1.2e-3f      /* extra (1-r) at min Annihil -> short ring */
#define HOWL_GIN       0.12f        /* input excitation into the resonator */
#define HOWL_DRIVE     2.4f         /* out-of-loop grit */
#define HOWL_DETUNE    1.012f       /* R resonator detune for stereo width */
/* Wet trim.
 *
 * The resonator's peak gain is GIN/(2*(1-r)), and r runs to 0.99997 at full
 * Annihil -- about 109x at the default setting and far more above it. Every
 * ring therefore slams howl_soft into its ceiling, so the wet path sits at FULL
 * SCALE whatever you play, while the dry it is mixed against sits nearer -14 dB.
 * The result measured +5.2 dB hotter than its own input and lifted the level of
 * the whole patch the moment the slot came on.
 *
 * Trimming the wet AFTER the clip keeps the saturation that makes this effect
 * what it is -- the timbre is unchanged, it is the same clipped waveform -- and
 * only brings its level into line with the rest of the pack. Fixing it at the
 * resonator input instead would have un-saturated it and made it a different,
 * politer effect. */
#define HOWL_WET_TRIM  0.42f
#define HOWL_WET       0.35f       /* howl rides at full scale -> keep it tame */
#define HOWL_DRY       0.30f

typedef struct HowlState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t pad;
    float y1L, y2L, y1R, y2R;

    /* Edit-driven knob latch (v3). The host clobbers the whole param block
     * on patch load AND when refocusing the effect in the chain UI (all
     * slots change at once, sometimes to garbage -> "very loud until you
     * wiggle"). A real knob turn changes ONE slot at a time. So: accept a
     * slot's value only when it is the lone change since the last block;
     * otherwise hold the last accepted value. Result: the effect keeps
     * sounding exactly as dialed across load/refocus. */
    float accKnob[3];                  /* accepted Tune/Annihil/Level (norm) */
    float prevRaw[3];                  /* raw slot values last block */
} HowlState;

static inline float howl_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

void HOWL_AUDIO_FUNC(unsigned int *ctx)
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
    if (end - base < (uintptr_t)sizeof(HowlState)) return;

    HowlState *st = (HowlState *)base;
    if (st->magic != HOWL_MAGIC || st->version != HOWL_VERSION || !st->initialized) {
        st->magic = HOWL_MAGIC;
        st->version = HOWL_VERSION;
        st->y1L = st->y2L = st->y1R = st->y2R = 0.0f;
        st->accKnob[0] = zoom_param_norm01(params[HOWL_TUNE_SLOT], HOWL_TUNE_DEFAULT_NORM);
        st->accKnob[1] = zoom_param_norm01(params[HOWL_ANNIHIL_SLOT], HOWL_ANNIHIL_DEFAULT_NORM);
        st->accKnob[2] = zoom_param_norm01(params[HOWL_MIX_SLOT], HOWL_MIX_DEFAULT_NORM);
        st->prevRaw[0] = st->prevRaw[1] = st->prevRaw[2] = -1.0f;
        st->initialized = 1u;
    }

    /* Edit-driven knob latch: accept only single-slot changes (knob turns);
     * bulk rewrites (load / chain refocus) are ignored and the last accepted
     * values keep sounding. A deliberate turn to zero IS accepted as zero. */
    {
        float raw[3];
        int k, changed = -1, nch = 0;
        raw[0] = params[HOWL_TUNE_SLOT];
        raw[1] = params[HOWL_ANNIHIL_SLOT];
        raw[2] = params[HOWL_MIX_SLOT];
        for (k = 0; k < 3; k++) {
            float d = raw[k] - st->prevRaw[k];
            if (d > 1.0e-6f || d < -1.0e-6f) { changed = k; nch++; }
            st->prevRaw[k] = raw[k];
        }
        if (nch == 1) {
            float v = raw[changed];
            float n = zoom_param_norm01(v, st->accKnob[changed]);
            st->accKnob[changed] = n;
        }
    }

    float tune   = st->accKnob[0];
    float annih  = st->accKnob[1];
    float level  = st->accKnob[2];
    /* True dry/wet crossfade. This was a wet SEND: dry sat at a fixed HOWL_DRY
     * and the knob only scaled the howl to a 0.45 ceiling, so the effect could
     * never reach full wet and its level never matched the rest of the pack. */
    float wetLvl = level;
    float dryLvl = 1.0f - level;

    float fc = HOWL_FC_MIN + tune * HOWL_FC_SPAN;
    float oma = 1.0f - annih;
    float r = 1.0f - (HOWL_GAP_MIN + HOWL_GAP_MAX * oma * oma);   /* always < 1 */
    float a2 = -r * r;

    float wL = HOWL_TWO_PI_SR * fc;
    float wR = wL * HOWL_DETUNE;
    float a1L = 2.0f * r * (1.0f - 0.5f * wL * wL);   /* small-angle cos */
    float a1R = 2.0f * r * (1.0f - 0.5f * wR * wR);

    float y1L = st->y1L, y2L = st->y2L, y1R = st->y1R, y2R = st->y2R;

    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];

        float yL = inL * HOWL_GIN + a1L * y1L + a2 * y2L;
        y2L = y1L; y1L = yL;
        float yR = inR * HOWL_GIN + a1R * y1R + a2 * y2R;
        y2R = y1R; y1R = yR;

        float wetL = howl_soft(yL * HOWL_DRIVE) * HOWL_WET_TRIM;
        float wetR = howl_soft(yR * HOWL_DRIVE) * HOWL_WET_TRIM;

        fxBuf[i]     = dryLvl * inL + wetLvl * wetL;
        fxBuf[i + 8] = dryLvl * inR + wetLvl * wetR;
    }

    st->y1L = y1L; st->y2L = y2L; st->y1R = y1R; st->y2R = y2R;
}
