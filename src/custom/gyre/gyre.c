/*
 * gyre.c -- Gyre: a loop you hold, that keeps spiralling, MS-70CDR.
 *
 * Spiral is a delay whose repeats climb; wind its feedback to maximum and it
 * self-oscillates into an endless loop you can still shape with the knobs. That
 * turned out to be the most interesting thing it does -- and the least usable,
 * because the only way out was a power cycle. Gyre is that behaviour built on
 * purpose, with a way in and a way out.
 *
 * The difference from Spiral is one design decision. Spiral reads its shifted
 * tap through ONE grain with a triangular window, so each pass through the loop
 * loses roughly half its energy. Unity feedback is therefore unreachable: the
 * repeats always die, unless something else in the path is quietly adding gain
 * (in Spiral's case its feedback clip, whose slope at the origin is 1.5 -- so
 * the loop crossed unity around Feedbk 69 rather than 100, and pinned there).
 *
 * Gyre reads TWO grains half a window apart with complementary triangular
 * windows. Linear crossfade means the pair sums to exactly 1 at every instant,
 * so the loop's throughput is unity by construction. Hold is then simply
 * Decay = 0: recirculate what is there, add nothing, lose nothing. It sustains
 * because the arithmetic says so, not because a gain happened to land above 1 --
 * and backing Decay off the stop lets it fade out cleanly, every time.
 *
 * 8 knobs. Size and Feed sit on knobs 1-2: those are the verbatim-stock LineSel
 * edit handlers, the most reliable pair in the pack, and they are the two you
 * reach for while playing.
 *   Size   (knob 1) loop length, ~40 ms .. ~2.9 s, squared so the short end
 *                   (where it reads as a stutter rather than a phrase) has room
 *   Feed   (knob 2) how much of what you play enters the loop. At 0 the loop is
 *                   sealed and what is captured is all there is; up, and it
 *                   keeps absorbing. This is the "record" control.
 *   Decay  (knob 3) 0 = hold forever. Above 0 the loop fades, from a slow bloom
 *                   down to a quick tail. This is the way out.
 *   Rise   (knob 4) per-pass pitch ratio: 0 = oct down, 50 = unity, 100 = oct up
 *   Glide  (knob 5) depth of the onset ramp on that ratio
 *   Span   (knob 6) how long that ramp takes, ~0.19 s .. ~8 s
 *   Tone   (knob 7) low-pass inside the loop -- the thing that makes a held loop
 *                   darken as it circulates instead of sitting still
 *   Mix    (knob 8) dry/wet
 *
 * Safe-DSP: no math lib (the ratio map is piecewise LINEAR, Span's coefficient a
 * cubic in the knob), no runtime divide, no modulo (power-of-two ring mask), no
 * switch (jump tables are unreachable in a ZDL and hard-freeze the DSP), no
 * static arrays, no .fardata, denormals flushed. The loop clip has UNITY slope
 * at the origin, so Decay means what it says rather than what the clip adds.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "gyre_params.h"

#ifndef GYRE_AUDIO_FUNC
#define GYRE_AUDIO_FUNC Fx_DLY_Gyre
#endif

#define GY_DO_PRAGMA(x) _Pragma(#x)
#define GY_EXPAND_PRAGMA(x) GY_DO_PRAGMA(x)
#define GY_CODE_SECTION(f) GY_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

GY_CODE_SECTION(GYRE_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define GY_MAGIC   0x47595245u   /* 'GYRE' */
#define GY_VERSION 1u

#define GY_BUF       131072u     /* 512 KB, ~2.97 s */
#define GY_MASK      (GY_BUF - 1u)

#define GY_GRAIN     1024        /* fixed power of two ... */
#define GY_HALF      512         /* ... so the half-offset is a literal too */
#define GY_INV_GRAIN 9.765625e-4f
#define GY_INV_HALF  1.953125e-3f

#define GY_RATIO_MIN 0.25f
#define GY_RATIO_MAX 4.0f

#define GY_D_FLOOR   1764        /* ~40 ms  */
#define GY_D_CEIL    129024      /* ~2.9 s, inside the ring with grain headroom */

#define GY_K_MIN     2.8e-6f     /* Span long end  (~8 s)    */
#define GY_K_MAX     1.16e-4f    /* Span short end (~0.19 s) */

#define GY_ENV_FAST  0.010f
#define GY_ENV_SLOW  0.0007f
#define GY_ONSET_MUL 1.9f
#define GY_ONSET_ADD 0.004f
#define GY_ARM_FRAC  0.45f
#define GY_PEAK_DEC  0.99993f
#define GY_COOLDOWN  3000

#define GY_DENORM    1.0e-18f

typedef struct GyreState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearPos;

    uint32_t writePos;
    float    tap;                /* leading grain read head */
    int32_t  grainT;
    float    lp;

    float    envFast, envSlow;
    float    ramp;
    float    peak;
    uint32_t armed;
    int32_t  cool;
} GyreState;

static inline float gy_abs(float x) { return x < 0.0f ? -x : x; }

/* Soft clip with UNITY slope at the origin.
 *
 * The usual cubic in this pack, 1.5x - 0.5x^3, has slope 1.5 at zero. Inside a
 * feedback loop that is 3.5 dB of gain the loop was never asked for, and it is
 * exactly what makes a "maximum feedback" setting mean "unescapable". f(x) =
 * x - x^3/6.75 reaches 1.0 at x = 1.5 with zero slope, so it saturates just as
 * smoothly while leaving the loop gain to the Decay knob alone. */
static inline float gy_clip1(float x)
{
    if (x > 1.5f) return 1.0f;
    if (x < -1.5f) return -1.0f;
    return x - x * x * x * (1.0f / 6.75f);
}

static inline float gy_read(const float *buf, float pos)
{
    int32_t i0 = (int32_t)pos;
    float fr = pos - (float)i0;
    uint32_t a = ((uint32_t)i0) & GY_MASK;
    uint32_t b = (a + 1u) & GY_MASK;
    return buf[a] * (1.0f - fr) + buf[b] * fr;
}

static inline float gy_wrap(float pos)
{
    if (pos >= (float)GY_BUF) pos -= (float)GY_BUF;
    if (pos < 0.0f) pos += (float)GY_BUF;
    return pos;
}

void GYRE_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(GyreState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)GY_BUF * 4u > end) return;

    GyreState *st = (GyreState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != GY_MAGIC || st->version != GY_VERSION || !st->initialized) {
        st->magic = GY_MAGIC;
        st->version = GY_VERSION;
        st->writePos = 0u;
        st->tap = 0.0f;
        st->grainT = 0;
        st->lp = 0.0f;
        st->envFast = st->envSlow = 0.0f;
        st->ramp = 1.0f;
        st->peak = 0.0f;
        st->armed = 1u;
        st->cool = 0;
        st->clearPos = 0u;
        st->initialized = 1u;
    }

    /* Clear the ring in chunks. A single-shot 512 KB clear inside one audio
     * block is long enough to be heard as a dropout. */
    if (st->clearPos < GY_BUF) {
        uint32_t n = st->clearPos, lim = n + 4096u;
        if (lim > GY_BUF) lim = GY_BUF;
        for (; n < lim; n++) buf[n] = 0.0f;
        st->clearPos = n;
    }

    float sz  = zoom_param_norm01(params[GYRE_SIZE_SLOT],  GYRE_SIZE_DEFAULT_NORM);
    float fd  = zoom_param_norm01(params[GYRE_FEED_SLOT],  GYRE_FEED_DEFAULT_NORM);
    float dc  = zoom_param_norm01(params[GYRE_DECAY_SLOT], GYRE_DECAY_DEFAULT_NORM);
    float rn  = zoom_param_norm01(params[GYRE_RISE_SLOT],  GYRE_RISE_DEFAULT_NORM);
    float gn  = zoom_param_norm01(params[GYRE_GLIDE_SLOT], GYRE_GLIDE_DEFAULT_NORM);
    float sn  = zoom_param_norm01(params[GYRE_SPAN_SLOT],  GYRE_SPAN_DEFAULT_NORM);
    float on  = zoom_param_norm01(params[GYRE_TONE_SLOT],  GYRE_TONE_DEFAULT_NORM);
    float mix = zoom_param_norm01(params[GYRE_MIX_SLOT],   GYRE_MIX_DEFAULT_NORM);

    /* Size: squared so the short end, where the loop reads as a stutter rather
     * than a phrase, gets most of the travel. */
    int32_t D = GY_D_FLOOR + (int32_t)(sz * sz * (float)(GY_D_CEIL - GY_D_FLOOR));
    if (D < GY_D_FLOOR) D = GY_D_FLOOR;
    else if (D > GY_D_CEIL) D = GY_D_CEIL;

    /* Decay 0 is a true hold: keep = 1, and the two-grain window sums to 1, so
     * the loop neither grows nor fades. Above 0 it fades, squared so the top of
     * the knob is a short tail and the bottom a very slow bloom. */
    float keep = 1.0f - dc * dc * 0.35f;
    float feed = fd * fd;

    /* Tap-overtake guard: the trailing grain sits GY_HALF behind the leading
     * one, so the pair needs a half-window more headroom than a single grain. */
    float ratioMax = 1.0f + (float)(D - GY_GRAIN - GY_HALF) * GY_INV_GRAIN;
    if (ratioMax > GY_RATIO_MAX) ratioMax = GY_RATIO_MAX;
    else if (ratioMax < 1.05f)   ratioMax = 1.05f;

    /* piecewise linear, unity at centre -- no exp2 */
    float baseRatio;
    if (rn < 0.5f) baseRatio = 0.5f + rn;
    else           baseRatio = 1.0f + (rn - 0.5f) * 2.0f;
    float glideDir = (rn >= 0.5f) ? 1.0f : -1.0f;
    float glideAmt = gn * 0.6f;

    float inv = 1.0f - sn;
    float rampK = GY_K_MIN + GY_K_MAX * inv * inv * inv;

    float lpCoef = 0.03f + on * 0.5f;

    uint32_t wp  = st->writePos;
    float tap    = st->tap;
    int32_t gt   = st->grainT;
    float lp     = st->lp;
    float envF   = st->envFast;
    float envS   = st->envSlow;
    float ramp   = st->ramp;
    float peak   = st->peak;
    uint32_t armed = st->armed;
    int32_t cool = st->cool;

    int i;
    for (i = 0; i < 8; i++) {
        float dry = 0.5f * (fxBuf[i] + fxBuf[i + 8]);

        float ax = gy_abs(dry);
        envF += GY_ENV_FAST * (ax - envF);
        envS += GY_ENV_SLOW * (ax - envS);
        peak = (envF > peak) ? envF : peak * GY_PEAK_DEC;
        if (envF < peak * GY_ARM_FRAC) armed = 1u;
        if (armed && cool <= 0 && envF > envS * GY_ONSET_MUL + GY_ONSET_ADD) {
            ramp = 0.0f;                 /* a phrase restarts the climb */
            cool = GY_COOLDOWN;
            armed = 0u;
        }
        if (cool > 0) cool--;
        ramp += rampK * (1.0f - ramp);

        float ratio = baseRatio * (1.0f + glideAmt * ramp * glideDir);
        if (ratio < GY_RATIO_MIN) ratio = GY_RATIO_MIN;
        else if (ratio > ratioMax) ratio = ratioMax;

        if (gt >= GY_GRAIN) {
            gt = 0;
            tap = gy_wrap((float)(int32_t)wp - (float)D);
        }

        /* TWO grains, half a window apart, with complementary LINEAR windows.
         *
         * w rises 0->1 across the grain and the trailing head uses 1-w, so the
         * pair sums to exactly 1 at every sample. That is what makes the loop
         * unity-throughput and Decay=0 an actual hold. A single triangular grain
         * (Spiral's approach) averages about half, which is why unity feedback
         * is unreachable there without something else adding gain. */
        float w = (float)gt * GY_INV_GRAIN;
        float tapB = gy_wrap(tap + (float)GY_HALF * ratio);
        float echo = gy_read(buf, tap) * w + gy_read(buf, tapB) * (1.0f - w);

        tap = gy_wrap(tap + ratio);
        gt++;

        lp += lpCoef * (echo - lp);      /* Tone inside the loop */
        if (lp < GY_DENORM && lp > -GY_DENORM) lp = 0.0f;

        buf[wp & GY_MASK] = gy_clip1(dry * feed + lp * keep);
        wp++;

        float out = dry * (1.0f - mix) + gy_clip1(lp) * mix;
        fxBuf[i]     = out;
        fxBuf[i + 8] = out;
    }

    st->writePos = wp;
    st->tap = tap;
    st->grainT = gt;
    st->lp = lp;
    st->envFast = envF;
    st->envSlow = envS;
    st->ramp = ramp;
    st->peak = peak;
    st->armed = armed;
    st->cool = cool;
}
