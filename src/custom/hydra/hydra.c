/*
 * hydra.c -- Hydra: two extra playback heads on one delay ring, MS-70CDR.
 *
 * Pedal port of tools/audio_preview/renderers/hydra.py. The dry goes into a
 * mono ring; two more heads read that ring at 2x and 0.5x, both re-triggered
 * every Window samples from one window behind the write head:
 *
 *   2x head   gap closes at 1 sample/sample, so over one window it consumes
 *             TWO windows of history and lands flush on the write head
 *             -> double-time ghost, octave up.
 *   0.5x head falls behind, covering half a window per window, max lag
 *             1.5 windows -> half-time drag, octave down.
 *
 * Window is what makes this one effect rather than two: a few ms puts the
 * re-trigger rate up at audio frequency, which IS granular pitch shifting
 * (octave-up / octave-down layers in time with the dry); 100 ms .. 0.7 s puts
 * it at rhythmic rates, so the layers become double-time hits and a half-time
 * drag. Aimed at drums.
 *
 * Window is now TEMPO-LOCKED. The re-trigger rate IS the rhythm of both ghost
 * layers, and a free sweep never lines up with a drum machine -- which is why
 * it "never got dialled in to tempo". 6 knobs, Div and Tempo on knobs 1-2 (the
 * verbatim-stock LineSel handlers, the most reliable pair in the pack):
 *   Div    (knob 1) window as a division of Tempo. Position 0 is Grain: a fixed
 *                   256-sample free-running window, i.e. the granular
 *                   octave-shifter mode above, which no musical division
 *                   reaches at any sane BPM. Above it: 1/32, 1/16T, 1/16, 1/8T,
 *                   1/8, dotted 1/8, 1/4.
 *   Tempo  (knob 2) BPM 40..240, read straight off the knob so the pedal's own
 *                   number IS the tempo. Ignored at Grain.
 *   Fast   (knob 3) level of the 2x head -- double-time ghost, octave up
 *   Slow   (knob 4) level of the 0.5x head -- half-time drag, octave down
 *   Tone   (knob 5) low-pass on the two layers only; the dry stays open
 *   Mix    (knob 6) dry/wet
 *
 * Safe-DSP: no math lib (smoothstep seam fade instead of a cosine, no pow --
 * the Window curve is a cubic), no runtime divide (the fade length is a fixed
 * power of two so its reciprocal is a literal), no modulo (power-of-two ring
 * mask), no switch (jump tables are unreachable in a ZDL and hard-freeze the
 * DSP), no static arrays, no float->unsigned casts. Ring lives in the ctx[3]
 * arena, cleared once at init. ctx[11]/ctx[12] magic shuttle preserved.
 * There is no feedback path, so the layers cannot self-oscillate.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "hydra_params.h"

#ifndef HYDRA_AUDIO_FUNC
#define HYDRA_AUDIO_FUNC Fx_DLY_Hydra
#endif

#define HYDRA_DO_PRAGMA(x) _Pragma(#x)
#define HYDRA_EXPAND_PRAGMA(x) HYDRA_DO_PRAGMA(x)
#define HYDRA_CODE_SECTION(f) HYDRA_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

HYDRA_CODE_SECTION(HYDRA_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define HY_MAGIC   0x48594452u   /* 'HYDR' */
#define HY_VERSION 1u

/* 131072 frames = 512 KB, ~2.97 s. The 0.5x head lags up to 1.5 windows, so
 * the ring is 4x the largest window -- comfortable margin. */
#define HY_BUF      131072u
#define HY_MASK     (HY_BUF - 1u)
#define HY_WIN_MIN  256          /* ~5.8 ms -- also the fixed Grain window */
/* Hard ceiling. The 2x head consumes TWO windows of history per window, so the
 * ring must hold 2*W with margin: 2*49152 = 98304 of 131072. A musical division
 * longer than this (1/4 below ~54 BPM) is clamped rather than allowed to read
 * past the write head. */
#define HY_WIN_MAX  49152
#define HY_SR_X60   2646000.0f   /* 44100*60: samples per quarter = this / BPM */
#define HY_BPM_MIN  40.0f
#define HY_BPM_MAX  240.0f
/* Quadratic seed for 1/BPM through 40/140/240 + 4 Newton-Raphson steps.
 * Multiplies only: a runtime divide would pull in __c6xabi_divf, a freeze
 * class. Worst relative error over the range is 2.0e-9. */
#define HY_RSEED_A  0.03630952f
#define HY_RSEED_B  (-3.125e-4f)
#define HY_RSEED_C  7.440476e-7f
#define HY_FADE     32           /* seam fade, fixed power of two ... */
#define HY_INV_FADE 0.03125f     /* ... so 1/HY_FADE is a literal, not a divide */
#define HY_DENORM   1.0e-18f

typedef struct HydraState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t writePos;
    float fastPos, slowPos;
    int32_t grainT;
    float lp;
} HydraState;

static inline float hy_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

/* Linear-interpolated ring read. pos is already wrapped into [0, HY_BUF). */
static inline float hy_read(const float *buf, float pos)
{
    int32_t i0 = (int32_t)pos;
    float fr = pos - (float)i0;
    uint32_t a = ((uint32_t)i0) & HY_MASK;
    uint32_t b = (a + 1u) & HY_MASK;
    return buf[a] * (1.0f - fr) + buf[b] * fr;
}

static inline float hy_wrap(float pos)
{
    if (pos >= (float)HY_BUF) pos -= (float)HY_BUF;
    if (pos < 0.0f) pos += (float)HY_BUF;
    return pos;
}

void HYDRA_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(HydraState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)HY_BUF * 4u > end) return;

    HydraState *st = (HydraState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != HY_MAGIC || st->version != HY_VERSION || !st->initialized) {
        st->magic = HY_MAGIC;
        st->version = HY_VERSION;
        st->writePos = 0u;
        st->fastPos = 0.0f;
        st->slowPos = 0.0f;
        st->grainT = 0;
        st->lp = 0.0f;
        uint32_t i;
        for (i = 0u; i < HY_BUF; i++) buf[i] = 0.0f;
        st->initialized = 1u;
    }

    float dv   = zoom_param_norm01(params[HYDRA_DIV_SLOT],   HYDRA_DIV_DEFAULT_NORM);
    float tp   = zoom_param_norm01(params[HYDRA_TEMPO_SLOT], HYDRA_TEMPO_DEFAULT_NORM);
    float fast = zoom_param_norm01(params[HYDRA_FAST_SLOT],   HYDRA_FAST_DEFAULT_NORM);
    float slow = zoom_param_norm01(params[HYDRA_SLOW_SLOT],   HYDRA_SLOW_DEFAULT_NORM);
    float tone = zoom_param_norm01(params[HYDRA_TONE_SLOT],   HYDRA_TONE_DEFAULT_NORM);
    float mix  = zoom_param_norm01(params[HYDRA_MIX_SLOT],    HYDRA_MIX_DEFAULT_NORM);

    /* Window used to be a free cubic sweep over 5.8ms..743ms, which is why it
     * "never got dialled in to tempo": the re-trigger rate IS the rhythm of the
     * two ghost layers, and nothing tied it to the beat. It is now a musical
     * division, so the 2x head lands on the subdivision and the 0.5x drag is
     * coherent with it. Position 0 keeps the old granular mode, which the
     * tempo ladder cannot reach at any sane BPM. */
    int32_t W;
    if (dv < 0.0625f) {
        W = HY_WIN_MIN;                          /* Grain: free-running */
    } else {
        float bpm = tp * HY_BPM_MAX;
        if (bpm < HY_BPM_MIN) bpm = HY_BPM_MIN;
        else if (bpm > HY_BPM_MAX) bpm = HY_BPM_MAX;

        float r = HY_RSEED_A + HY_RSEED_B * bpm + HY_RSEED_C * bpm * bpm;
        r = r * (2.0f - bpm * r);
        r = r * (2.0f - bpm * r);
        r = r * (2.0f - bpm * r);
        r = r * (2.0f - bpm * r);
        float quarter = HY_SR_X60 * r;

        /* if/else, never switch: a jump table is unreachable in a ZDL. */
        float divMul;
        if      (dv < 0.1875f) divMul = 0.125f;              /* 1/32         */
        else if (dv < 0.3125f) divMul = 0.1666667f;          /* 1/16 triplet */
        else if (dv < 0.4375f) divMul = 0.25f;               /* 1/16         */
        else if (dv < 0.5625f) divMul = 0.3333333f;          /* 1/8 triplet  */
        else if (dv < 0.6875f) divMul = 0.5f;                /* 1/8          */
        else if (dv < 0.8125f) divMul = 0.75f;               /* dotted 1/8   */
        else                   divMul = 1.0f;                /* 1/4          */

        W = (int32_t)(quarter * divMul);
    }
    if (W < HY_WIN_MIN) W = HY_WIN_MIN;
    else if (W > HY_WIN_MAX) W = HY_WIN_MAX;

    float lpCoef = 0.02f + tone * 0.55f;

    uint32_t wp   = st->writePos;
    float fastPos = st->fastPos;
    float slowPos = st->slowPos;
    int32_t gt    = st->grainT;
    float lp      = st->lp;

    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];
        float dry = 0.5f * (inL + inR);

        buf[wp & HY_MASK] = dry;

        if (gt >= W) {                      /* re-trigger both heads one window back */
            gt = 0;
            float start = hy_wrap((float)(int32_t)wp - (float)W);
            fastPos = start;
            slowPos = start;
        }

        /* smoothstep seam fade -- no cosine, and the reciprocal is a literal */
        float env;
        if (gt < HY_FADE) {
            float t = (float)gt * HY_INV_FADE;
            env = t * t * (3.0f - 2.0f * t);
        } else if (gt > W - HY_FADE) {
            float t = (float)(W - gt) * HY_INV_FADE;
            env = t * t * (3.0f - 2.0f * t);
        } else {
            env = 1.0f;
        }

        float f = hy_read(buf, fastPos);
        float s = hy_read(buf, slowPos);
        fastPos = hy_wrap(fastPos + 2.0f);
        slowPos = hy_wrap(slowPos + 0.5f);
        gt++;
        wp++;

        float layers = (f * fast + s * slow) * env;
        lp += lpCoef * (layers - lp);
        if (lp < HY_DENORM && lp > -HY_DENORM) lp = 0.0f;   /* flush denormals */

        float wet = hy_soft(dry + lp);
        float out = dry + (wet - dry) * mix;

        fxBuf[i]     = out;
        fxBuf[i + 8] = out;
    }

    st->writePos = wp;
    st->fastPos = fastPos;
    st->slowPos = slowPos;
    st->grainT = gt;
    st->lp = lp;
}
