/*
 * edgewatch.c -- EdgeWatch: can an effect see the footswitch, and does audio
 * still reach it while bypassed? MS-70CDR hardware probe.
 *
 * A freeze effect needs a MOMENT -- something has to say "hold this". There is
 * no footswitch API here, so the only candidate trigger is the slot's own
 * bypass bit, params[0]. CtxWatch established two things that make that
 * plausible: the host calls a slot's audio function even when the slot is
 * bypassed, and the output is still audible in that state. What it did NOT
 * establish is whether the params[0] TRANSITION is visible promptly, which is
 * the single assumption the whole freeze design rests on.
 *
 * It also answers a second question the design needs: a freeze must be
 * ALREADY RECORDING at the instant you stomp, so input audio has to be
 * reaching the effect while it is bypassed. Nothing so far has tested that.
 *
 * What you hear (silent otherwise -- see the CtxWatch notes on why a probe that
 * hums continuously is unreadable):
 *
 *   boot                two MID beeps          alive and armed
 *   slot OFF -> ON      two HIGH beeps         rising edge seen
 *   slot ON  -> OFF     one LOW beep           falling edge seen. Hearing this
 *                                              AT ALL also re-proves the effect
 *                                              keeps running while bypassed.
 *   bypassed + playing  one short MID tick     input audio IS delivered while
 *                       (at most 1/second)     bypassed -- the freeze can record
 *
 * Reading the result:
 *   beeps land the instant you stomp        -> the edge is usable, build the freeze
 *   beeps lag, or only one direction fires  -> params[0] is not a reliable trigger
 *   ticks while bypassed                    -> "always recording" works
 *   no ticks while bypassed                 -> the ring would be empty at capture
 *                                              time; freeze must trigger on
 *                                              onset instead
 *
 * Deliberately does NOT return early on params[0]: returning is exactly the
 * behaviour under test. Knobs are hardcoded, because a probe must not depend on
 * the mechanism it is testing (PE writes zeros into slot 4-6 params).
 *
 * Safe-DSP: no switch (jump tables are unreachable in a ZDL and hard-freeze the
 * DSP), no CALLs or helper calls, no runtime divide, no modulo, no static
 * arrays, no .fardata, no float->unsigned casts, denormals flushed.
 */

#include <stdint.h>

#ifndef EDGEWATCH_AUDIO_FUNC
#define EDGEWATCH_AUDIO_FUNC Fx_SFX_EdgeWatch
#endif

#define EW_DO_PRAGMA(x) _Pragma(#x)
#define EW_EXPAND_PRAGMA(x) EW_DO_PRAGMA(x)
#define EW_CODE_SECTION(f) EW_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

EW_CODE_SECTION(EDGEWATCH_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define EW_MAGIC   0x45444757u   /* 'EDGW' */
#define EW_VERSION 1u

#define EW_AMP        0.12f
#define EW_BEEP_ON    5292       /* 120 ms -- long enough to count, short enough
                                  * not to smear two beeps into one */
#define EW_BEEP_OFF   4410       /* 100 ms */
#define EW_TICK_ON    1764       /* 40 ms */
#define EW_SETTLE     88200      /* 2 s of silence before arming */
#define EW_TICK_GAP   44100      /* at most one input tick per second */
#define EW_EDGE_LOCK  3528       /* 80 ms refractory: a mechanical switch can
                                  * bounce, and one stomp must not read as many */
#define EW_IN_THRESH  0.01f      /* input considered present above this */
#define EW_ENV_COEF   0.004f
#define EW_DENORM     1.0e-18f

/* Pitch selectors. tone increments once per sample, so masking bit N gives a
 * square wave of period 2N samples. */
#define EW_HIGH  16u             /* ~1.4 kHz */
#define EW_MID   32u             /* ~690 Hz  */
#define EW_LOW   96u             /* ~230 Hz  */

typedef struct EdgeState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t settle;
    uint32_t prevOn;         /* last seen params[0] state */
    uint32_t booted;
    uint32_t tone;
    uint32_t beepTone;       /* pitch mask for the burst in progress */
    int32_t  beepsLeft;
    int32_t  beepPhase;
    int32_t  edgeLock;       /* debounce */
    int32_t  tickGap;        /* rate limit on the input-present tick */
    float    env;
} EdgeState;

static inline float ew_flush(float x)
{
    if (x < EW_DENORM && x > -EW_DENORM) return 0.0f;
    return x;
}

static inline float ew_abs(float x) { return x < 0.0f ? -x : x; }

void EDGEWATCH_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* NO early return on params[0] -- that is the behaviour under test. */

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u) return;
    if (base + sizeof(EdgeState) > end) return;

    EdgeState *st = (EdgeState *)base;

    if (st->magic != EW_MAGIC || st->version != EW_VERSION || !st->initialized) {
        st->magic = EW_MAGIC;
        st->version = EW_VERSION;
        st->settle = EW_SETTLE;
        st->prevOn = (params[0] >= 0.5f) ? 1u : 0u;
        st->booted = 0u;
        st->tone = 0u;
        st->beepTone = EW_MID;
        st->beepsLeft = 0;
        st->beepPhase = 0;
        st->edgeLock = 0;
        st->tickGap = 0;
        st->env = 0.0f;
        st->initialized = 1u;
    }

    uint32_t nowOn = (params[0] >= 0.5f) ? 1u : 0u;

    if (st->settle > 0u) {
        st->settle = (st->settle > 8u) ? (st->settle - 8u) : 0u;
        st->prevOn = nowOn;                  /* don't report the initial state */
        if (st->settle == 0u && !st->booted) {
            st->booted = 1u;
            st->beepTone = EW_MID;
            st->beepsLeft = 2;
            st->beepPhase = EW_BEEP_ON + EW_BEEP_OFF;
        }
    } else if (st->edgeLock <= 0 && nowOn != st->prevOn) {
        /* The whole point of the probe. Rising and falling are given different
         * pitches AND different counts so one cannot be mistaken for the other
         * when you are looking at the pedal rather than the screen. */
        st->beepTone  = nowOn ? EW_HIGH : EW_LOW;
        st->beepsLeft = nowOn ? 2 : 1;
        st->beepPhase = EW_BEEP_ON + EW_BEEP_OFF;
        st->prevOn = nowOn;
        st->edgeLock = EW_EDGE_LOCK;
    }
    if (st->edgeLock > 0) st->edgeLock -= 8;

    uint32_t tone   = st->tone;
    int32_t beeps   = st->beepsLeft;
    int32_t phase   = st->beepPhase;
    uint32_t bmask  = st->beepTone;
    int32_t tickGap = st->tickGap;
    float env       = st->env;

    int i;
    for (i = 0; i < 8; i++) {
        tone++;

        /* Input-presence follower. Read BEFORE we add anything, so we measure
         * what the host handed us rather than our own beeps. */
        float in = 0.5f * (fxBuf[i] + fxBuf[i + 8]);
        float ax = ew_abs(in);
        env += EW_ENV_COEF * (ax - env);

        /* While bypassed, a tick proves input audio is still arriving -- the
         * thing "always recording" depends on. Rate limited so a held chord
         * does not turn into a stutter. */
        if (!nowOn && beeps <= 0 && tickGap <= 0 && env > EW_IN_THRESH) {
            beeps  = 1;
            bmask  = EW_MID;
            phase  = EW_TICK_ON;
            tickGap = EW_TICK_GAP;
        }
        if (tickGap > 0) tickGap--;

        float v = 0.0f;
        if (beeps > 0) {
            if (phase > EW_BEEP_OFF || bmask == EW_MID) {
                v = (tone & bmask) ? EW_AMP : -EW_AMP;
            }
            phase--;
            if (phase <= 0) {
                beeps--;
                phase = (beeps > 0) ? (EW_BEEP_ON + EW_BEEP_OFF) : 0;
            }
        }

        /* += so the dry signal passes through untouched either way. */
        fxBuf[i]     += v;
        fxBuf[i + 8] += v;
        outBuf[i]     += v;
        outBuf[i + 8] += v;
    }

    st->tone = tone;
    st->beepsLeft = beeps;
    st->beepPhase = phase;
    st->beepTone = bmask;
    st->tickGap = tickGap;
    st->env = ew_flush(env);
}
