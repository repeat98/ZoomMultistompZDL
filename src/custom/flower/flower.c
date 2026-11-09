/*
 * flower.c -- Flower: a Korg-"Random"-style sample-and-hold resonant step
 * filter (the Deftones "Digital Bath" sound) for the Zoom MS-70CDR.
 *
 * Pedal port of the desktop design in
 * tools/audio_preview/renderers/flower.py. The pedal build is intentionally
 * 2 knobs (Rate, Mix) to stay on the hardware-proven UI shape; Reso, sweep
 * range, and center frequency are baked to the Digital Bath character. The
 * 6-knob desktop manifest.json keeps the full controls for previewing.
 *
 * Safe-DSP compliance (docs/SAFE-DSP-RULES.md):
 *   - No math library: the random cutoff is linear (no powf), and the
 *     Chamberlin SVF coefficient uses the small-angle approximation
 *     f1 ~= 2*pi*fc/sr (accurate for the baked <=3 kHz cutoff range), so
 *     no sinf/tanf.
 *   - No runtime float divide: the S&H clock is a phase accumulator scaled
 *     by the compile-time constant 1/SR. uint->float is done via a masked
 *     signed conversion to dodge __c6xabi unsigned-convert helpers.
 *   - Persistent per-instance state lives in the host ctx[3] arena (the
 *     StChorus-proven mechanism), validated before any access; an invalid
 *     descriptor degrades to dry pass-through, never a freeze.
 *   - ctx[11]/ctx[12] magic shuttle preserved.
 *   - Output is hard-clamped so a resonant peak cannot blow up.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "flower_params.h"

#ifndef FLOWER_AUDIO_FUNC
#define FLOWER_AUDIO_FUNC Fx_MOD_Flower
#endif

#define FLOWER_DO_PRAGMA(x) _Pragma(#x)
#define FLOWER_EXPAND_PRAGMA(x) FLOWER_DO_PRAGMA(x)
#define FLOWER_CODE_SECTION(f) FLOWER_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

FLOWER_CODE_SECTION(FLOWER_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define FLOWER_MAGIC    0x464C5752u    /* 'FLWR' */
#define FLOWER_VERSION  1u

#define FLOWER_SR        44100.0f
#define FLOWER_INV_SR    (1.0f / FLOWER_SR)
#define FLOWER_TWO_PI_SR (6.2831853f / FLOWER_SR)   /* f1 = this * cutoff */
#define FLOWER_CUT_MIN   150.0f
#define FLOWER_CUT_SPAN  2850.0f       /* random cutoff 150..3000 Hz */
#define FLOWER_RESO_K    0.18f         /* SVF damping; low = resonant (~Q5.5) */
#define FLOWER_SLEW      0.05f         /* cutoff glide per sample */
#define FLOWER_BP_MIX    0.9f          /* bandpass blend to expose the peak */
#define FLOWER_CLAMP     2.0f

typedef struct FlowerState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t pad;

    float lowL, bandL, cutL, tgtL, phaseL;
    float lowR, bandR, cutR, tgtR, phaseR;
    uint32_t rngL, rngR;
} FlowerState;

static inline uint32_t flower_xs(uint32_t *s)
{
    uint32_t x = *s;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *s = x;
    return x;
}

/* uint32 -> [0,1): take top 23 bits so the value fits a positive int and a
 * float mantissa exactly, then a hardware int->float convert. */
static inline float flower_rand01(uint32_t *s)
{
    uint32_t u = flower_xs(s) >> 9;          /* 0 .. 2^23-1 */
    return (float)(int)u * (1.0f / 8388608.0f);
}

static inline void flower_reset(FlowerState *st)
{
    st->magic = FLOWER_MAGIC;
    st->version = FLOWER_VERSION;
    st->lowL = st->bandL = 0.0f;
    st->lowR = st->bandR = 0.0f;
    st->cutL = st->cutR = 600.0f;
    st->tgtL = st->tgtR = 600.0f;
    st->phaseL = 0.0f;
    st->phaseR = 0.5f;            /* offset so L/R sequences decorrelate */
    st->rngL = 0x12345678u;
    st->rngR = 0x9E3779B9u;
    st->initialized = 1u;
}

void FLOWER_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);

    /* Magic shuttle - preserve every audio call. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;     /* bypass: dry already sits in fxBuf */

    /* Validate the host-managed state arena before touching it. */
    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u) return;
    if (end - base < (uintptr_t)sizeof(FlowerState)) return;

    FlowerState *st = (FlowerState *)base;
    if (st->magic != FLOWER_MAGIC || st->version != FLOWER_VERSION || !st->initialized) {
        flower_reset(st);
    }

    float rate = zoom_param_norm01(params[FLOWER_RATE_SLOT], FLOWER_RATE_DEFAULT_NORM);
    float mix  = zoom_param_norm01(params[FLOWER_MIX_SLOT],  FLOWER_MIX_DEFAULT_NORM);

    float rateHz   = 0.5f + rate * 13.5f;        /* ~0.5..14 steps/sec */
    float phaseInc = rateHz * FLOWER_INV_SR;     /* no runtime divide */
    float wetMix   = mix;
    float dryMix   = 1.0f - mix;

    /* Left channel: samples 0..7. */
    {
        float low = st->lowL, band = st->bandL, cut = st->cutL, tgt = st->tgtL, ph = st->phaseL;
        uint32_t rng = st->rngL;
        int i;
        for (i = 0; i < 8; i++) {
            ph += phaseInc;
            if (ph >= 1.0f) {
                ph -= 1.0f;
                tgt = FLOWER_CUT_MIN + flower_rand01(&rng) * FLOWER_CUT_SPAN;
            }
            cut += FLOWER_SLEW * (tgt - cut);
            float f1 = FLOWER_TWO_PI_SR * cut;
            float in = fxBuf[i];
            low += f1 * band;
            float high = in - low - FLOWER_RESO_K * band;
            band += f1 * high;
            float wet = low + FLOWER_BP_MIX * band;
            if (wet > FLOWER_CLAMP) wet = FLOWER_CLAMP;
            else if (wet < -FLOWER_CLAMP) wet = -FLOWER_CLAMP;
            fxBuf[i] = dryMix * in + wetMix * wet;
        }
        st->lowL = low; st->bandL = band; st->cutL = cut; st->tgtL = tgt; st->phaseL = ph; st->rngL = rng;
    }

    /* Right channel: samples 8..15 (independent random sequence). */
    {
        float low = st->lowR, band = st->bandR, cut = st->cutR, tgt = st->tgtR, ph = st->phaseR;
        uint32_t rng = st->rngR;
        int i;
        for (i = 8; i < 16; i++) {
            ph += phaseInc;
            if (ph >= 1.0f) {
                ph -= 1.0f;
                tgt = FLOWER_CUT_MIN + flower_rand01(&rng) * FLOWER_CUT_SPAN;
            }
            cut += FLOWER_SLEW * (tgt - cut);
            float f1 = FLOWER_TWO_PI_SR * cut;
            float in = fxBuf[i];
            low += f1 * band;
            float high = in - low - FLOWER_RESO_K * band;
            band += f1 * high;
            float wet = low + FLOWER_BP_MIX * band;
            if (wet > FLOWER_CLAMP) wet = FLOWER_CLAMP;
            else if (wet < -FLOWER_CLAMP) wet = -FLOWER_CLAMP;
            fxBuf[i] = dryMix * in + wetMix * wet;
        }
        st->lowR = low; st->bandR = band; st->cutR = cut; st->tgtR = tgt; st->phaseR = ph; st->rngR = rng;
    }
}
