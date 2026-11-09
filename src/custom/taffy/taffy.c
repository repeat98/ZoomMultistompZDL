/*
 * taffy.c -- Taffy: Red Panda Tensor-style live tape warp, MS-70CDR.
 *
 * The input is continuously recorded into a ring; a playback head reads it
 * back at a variable speed, from full reverse through stop to double speed.
 * 5 knobs:
 *   Speed  (params[5]) - the tape-motor speed the head ALWAYS trends toward:
 *                        0 = -1x (full reverse), 25 = stop, 50 = +1x (normal),
 *                        100 = +2x (octave up). This is the anchor.
 *   Chance (params[6]) - how often random speed/direction slips happen.
 *   Depth  (params[7]) - how far a slip deviates from Speed. 0 = slips do
 *                        nothing (pure speed control); 1 = fully random warps.
 *   Glide  (params[8]) - tape-motor smoothness: 0 = snappy/abrupt speed jumps,
 *                        1 = long smooth pitch glides.
 *   Mix    (params[9]) - dry/wet.
 *
 * When the head runs off the usable window (catches the record head at +2x,
 * or falls off the back at -1x) it jumps to a fresh spot through a short
 * two-head crossfade -- the chunked repeat/rewind feel of the Tensor.
 *
 * Safe-DSP: no math lib, no runtime divide (xorshift RNG, linear fades),
 * no static arrays. Mono ring in the ctx[3] arena (validated + lazily
 * cleared). ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "taffy_params.h"

#ifndef TAFFY_AUDIO_FUNC
#define TAFFY_AUDIO_FUNC Fx_DLY_Taffy
#endif

#define TAFFY_DO_PRAGMA(x) _Pragma(#x)
#define TAFFY_EXPAND_PRAGMA(x) TAFFY_DO_PRAGMA(x)
#define TAFFY_CODE_SECTION(f) TAFFY_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

TAFFY_CODE_SECTION(TAFFY_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define TAFFY_MAGIC   0x54414659u   /* 'TAFY' */
#define TAFFY_VERSION 1u

#define TF_BUF        32768u        /* mono ring, ~0.74 s (power of 2) */
#define TF_MASK       (TF_BUF - 1u)
#define TF_CLEAR_STEP 4096u
#define TF_DMIN       256.0f        /* safety gap behind the record head */
#define TF_DMAX       32000.0f      /* oldest usable material */
#define TF_DHOME      2048.0f       /* head lands here after a jump */
#define TF_FADE       384u          /* crossfade length (samples) */
#define TF_FADE_INC   (1.0f / 384.0f)
#define TF_EVT        2048u         /* random-slip decision interval (~46 ms) */
#define TF_SLEW       0.001f        /* tape-motor speed glide */

typedef struct TaffyState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t writePos;
    float dA;                       /* active head: delay behind writePos */
    float dB;                       /* incoming head during a crossfade */
    float fade;                     /* 0 = only A; (0,1) = fading to B */
    float curSpeed;
    float tgtSpeed;
    uint32_t evtCount;
    uint32_t rng;
} TaffyState;

static inline float tf_read(const float *buf, uint32_t wp, float d)
{
    int di = (int)d;
    float fr = d - (float)di;
    uint32_t idx0 = (wp - (uint32_t)di) & TF_MASK;
    uint32_t idx1 = (idx0 - 1u) & TF_MASK;
    return buf[idx0] * (1.0f - fr) + buf[idx1] * fr;
}

static inline uint32_t tf_rng(uint32_t r)
{
    r ^= r << 13;
    r ^= r >> 17;
    r ^= r << 5;
    return r;
}

/* top 24 bits -> [0, 1) */
#define TF_RAND01(r) ((float)((r) >> 8) * 5.9604645e-8f)

void TAFFY_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(TaffyState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)TF_BUF * 4u > end) return;

    TaffyState *st = (TaffyState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != TAFFY_MAGIC || st->version != TAFFY_VERSION) {
        st->magic = TAFFY_MAGIC;
        st->version = TAFFY_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->writePos = 0u;
        st->dA = TF_DHOME;
        st->dB = TF_DHOME;
        st->fade = 0.0f;
        st->curSpeed = 1.0f;
        st->tgtSpeed = 1.0f;
        st->evtCount = 0u;
        st->rng = 0x1234567u;
    }

    if (!st->initialized) {
        uint32_t e = st->clearIndex + TF_CLEAR_STEP;
        if (e > TF_BUF) e = TF_BUF;
        uint32_t i;
        for (i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= TF_BUF) st->initialized = 1u;
        return;
    }

    float speedK = zoom_param_norm01(params[TAFFY_SPEED_SLOT], TAFFY_SPEED_DEFAULT_NORM);
    float chance = zoom_param_norm01(params[TAFFY_CHANCE_SLOT], TAFFY_CHANCE_DEFAULT_NORM);
    float depth  = zoom_param_norm01(params[TAFFY_DEPTH_SLOT], TAFFY_DEPTH_DEFAULT_NORM);
    float glide  = zoom_param_norm01(params[TAFFY_GLIDE_SLOT], TAFFY_GLIDE_DEFAULT_NORM);
    float mix    = zoom_param_norm01(params[TAFFY_MIX_SLOT], TAFFY_MIX_DEFAULT_NORM);

    /* knob -> speed: -1x .. stop .. +1x (noon) .. +2x */
    float knobSpeed;
    if (speedK < 0.5f) knobSpeed = -1.0f + 4.0f * speedK;
    else               knobSpeed = 1.0f + 2.0f * (speedK - 0.5f);
    float wet = mix;
    float dry = 1.0f - mix;

    /* Glide -> motor slew: high glide = smaller step = smoother pitch bends. */
    float slew = 0.0005f + (1.0f - glide) * 0.015f;   /* ~0.0005 (smooth) .. ~0.0155 (snappy) */
    float slipProb = chance * chance;                 /* per-decision slip probability */

    uint32_t wp = st->writePos;
    float dA = st->dA, dB = st->dB, fade = st->fade;
    float cur = st->curSpeed, tgt = st->tgtSpeed;
    uint32_t evt = st->evtCount, rng = st->rng;

    /* with Chance at zero the head simply follows the knob */
    if (chance <= 0.001f) tgt = knobSpeed;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        buf[wp] = 0.5f * (inL + inR);

        /* random slips: every TF_EVT samples, maybe re-decide. Slips are now
         * DEVIATIONS FROM the knob speed, scaled by Depth, so Speed stays the
         * audible anchor and Depth controls how wild the warps get. */
        evt++;
        if (evt >= TF_EVT) {
            evt = 0u;
            rng = tf_rng(rng);
            if (TF_RAND01(rng) < slipProb) {
                rng = tf_rng(rng);
                /* pick 0..4 without integer modulo (runtime divide = banned):
                 * 3 bits 0..7, fold 5..7 down (slight bias, fine for slips) */
                uint32_t pick = (rng >> 4) & 7u;
                if (pick > 4u) pick -= 5u;
                float slipSpeed;
                if (pick == 0u)      slipSpeed = -1.0f;   /* rewind */
                else if (pick == 1u) slipSpeed = -0.5f;   /* slow rewind */
                else if (pick == 2u) slipSpeed = 0.5f;    /* octave down */
                else if (pick == 3u) slipSpeed = 1.0f;    /* normal */
                else                 slipSpeed = 2.0f;    /* octave up */
                /* blend from the knob speed toward the slip target by Depth */
                tgt = knobSpeed + depth * (slipSpeed - knobSpeed);
                rng = tf_rng(rng);
                if (fade <= 0.0f && TF_RAND01(rng) < 0.3f * depth) {
                    /* relocate: jump the head somewhere fresh (Depth-gated) */
                    rng = tf_rng(rng);
                    dB = TF_DMIN + TF_RAND01(rng) * (TF_DMAX * 0.5f);
                    fade = TF_FADE_INC;
                }
            } else {
                tgt = knobSpeed;                    /* between slips, sit at the knob speed */
            }
        }

        /* tape-motor glide toward the target speed (Glide sets the rate) */
        cur += (tgt - cur) * slew;

        /* both heads move together through the material */
        float dd = 1.0f - cur;
        dA += dd;
        if (fade > 0.0f) dB += dd;

        /* active head off the usable window -> start a jump crossfade */
        if (fade <= 0.0f && (dA < TF_DMIN || dA > TF_DMAX)) {
            dB = TF_DHOME;
            fade = TF_FADE_INC;
        }
        /* incoming head must stay legal no matter what */
        if (dB < TF_DMIN) dB = TF_DMIN;
        else if (dB > TF_DMAX) dB = TF_DMAX;
        if (dA < 1.0f) dA = 1.0f;
        else if (dA > (float)(TF_BUF - 2u)) dA = (float)(TF_BUF - 2u);

        float warp;
        if (fade > 0.0f) {
            float a = tf_read(buf, wp, dA);
            float b = tf_read(buf, wp, dB);
            warp = a * (1.0f - fade) + b * fade;
            fade += TF_FADE_INC;
            if (fade >= 1.0f) {     /* B becomes the active head */
                dA = dB;
                fade = 0.0f;
            }
        } else {
            warp = tf_read(buf, wp, dA);
        }

        fxBuf[f]     = dry * inL + wet * warp;
        fxBuf[f + 8] = dry * inR + wet * warp;

        wp = (wp + 1u) & TF_MASK;
    }

    st->writePos = wp;
    st->dA = dA;
    st->dB = dB;
    st->fade = fade;
    st->curSpeed = cur;
    st->tgtSpeed = tgt;
    st->evtCount = evt;
    st->rng = rng;
}
