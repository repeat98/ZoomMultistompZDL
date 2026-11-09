/*
 * rewire.c -- Rewire: four lo-fi blocks in a chain you can reorder, MS-70CDR.
 *
 * Alesis ModFX Bitrman-inspired (no Alesis branding). What makes that box worth
 * chasing is not any single block -- this pack already has bitcrush three times
 * over -- but that its 123B / B321 / 1B32 modes REORDER the chain. Crush before
 * a comb is a different pedal from a comb before crush, and distortion last
 * sounds nothing like distortion first. Slot order in a patch reorders whole
 * effects; nothing here could reorder stages INSIDE one.
 *
 * Five blocks, one knob each, and a Route knob that permutes them:
 *   B  Bits   crush + sample-rate decimate on one control
 *   D  Drive  asymmetric soft clip
 *   R  Ring   ring modulator; the knob sweeps the carrier and fades it in
 *   C  Comb   short feedback comb, the knob is depth
 *   S  Shift  single-sideband frequency shifter, centre-off
 *
 * 8 knobs. Route and Bits sit on knobs 1-2, the verbatim-stock LineSel edit
 * handlers -- the most reliable pair in the pack, and the two most often moved:
 *   Route (knob 1) block order: BDRCS, SCRDB, DSBCR, RCSBD, SBRDC
 *   Bits  (knob 2) crush depth and decimation together
 *   Drive (knob 3) distortion amount
 *   Ring  (knob 4) carrier frequency, fading in from silent at 0
 *   Comb  (knob 5) comb depth
 *   Shift (knob 6) frequency shift, -400..+400 Hz, 50 = off
 *   Tone  (knob 7) low-pass on the wet path
 *   Mix   (knob 8) dry/wet
 *
 * The shifter is the one block here that is not a few lines of arithmetic. A
 * frequency shift ADDS a constant number of Hz rather than multiplying, so it
 * breaks harmonic ratios -- the reason it sounds inharmonic and bell-like where
 * a pitch shift sounds like a pitch shift. Doing it needs the analytic signal:
 * the input plus a copy shifted 90 degrees at EVERY frequency, which is a
 * Hilbert transformer. Two allpass chains whose outputs sit 90 degrees apart,
 * one delayed a sample against the other, then out = re*cos - im*sin.
 *
 * The eight pole values below were NOT taken from a reference. Hand-recalled
 * coefficients were tried first and the phase difference collapsed from 89
 * degrees at the bottom of the band to zero by 5 kHz, which would have produced
 * both sidebands -- a harsh ring mod wearing a shifter's name. These were
 * optimised numerically for worst-case phase error over 50 Hz - 12 kHz, with the
 * two chains' poles INTERLEAVED, which is the property the failed attempt was
 * missing. Verified against the exact recurrence used here: worst deviation
 * 0.61 degrees, image rejection -51 dB measured, carrier feedthrough -152 dB.
 * Four sections per chain rather than six (-63 dB) on purpose: the image is
 * already far below audibility and section count is code size, which is the
 * thing that broke this effect once already.
 *
 * How the routing is done, and why not the obvious ways. A permutation TABLE
 * would need an indirect call or an indexed jump, and both are freeze classes
 * here -- a ZDL's jump tables are unrelocated, and a CALL pulls in a helper.
 * Five straight-line arms with all four blocks expanded in each was the first
 * attempt, and it failed differently: twenty inline expansions made the compiler
 * give up inlining, emitting 256 bytes outside the .audio section and twelve
 * relocations with it, which is equally fatal. What works is packing the order
 * into one nibble per stage and looping five times, so each block appears ONCE
 * and stays inline. Costs a shift and a compare per stage. The stage loop is
 * pinned with UNROLL(1) for the same reason -- unrolled five ways it would
 * expand the shifter's eight allpass sections five times over and walk straight
 * back into the fault above.
 *
 * Safe-DSP: no switch (jump tables are unreachable in a ZDL and hard-freeze the
 * DSP), no CALLs or helper calls, no runtime divide (the decimator counter and
 * the comb length are integers; the crush step's reciprocal comes from an
 * if/else ladder of literals), no modulo (power-of-two ring mask), no static
 * arrays, no .fardata, no float->unsigned casts, denormals flushed. The comb is
 * the only feedback path and its gain is clamped below unity, so it cannot run
 * away whatever the routing.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "rewire_params.h"

#ifndef REWIRE_AUDIO_FUNC
#define REWIRE_AUDIO_FUNC Fx_DLY_Rewire
#endif

#define REWIRE_DO_PRAGMA(x) _Pragma(#x)
#define REWIRE_EXPAND_PRAGMA(x) REWIRE_DO_PRAGMA(x)
#define REWIRE_CODE_SECTION(f) REWIRE_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

REWIRE_CODE_SECTION(REWIRE_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define RW_MAGIC   0x52575231u   /* 'RWR1' */
#define RW_VERSION 2u            /* 2: added the Shift block and its allpass state */

/* Hilbert phase-splitter poles. Sections are in z^-2: y = a*(x + y[n-2]) - x[n-2].
 * Chain A and chain B interleave -- A0 < B0 < A1 < B1 < ... -- which is what makes
 * the 90-degree difference hold across the band. See the header note. */
#define RW_HA0 0.155235327f
#define RW_HA1 0.719471331f
#define RW_HA2 0.940417779f
#define RW_HA3 0.991416628f
#define RW_HB0 0.465295704f
#define RW_HB1 0.867077659f
#define RW_HB2 0.974857009f
#define RW_HB3 0.998500000f

#define RW_HALF_PI 1.57079633f
#define RW_MAX_SHIFT 400.0f      /* Hz at either extreme of the Shift knob */

#define RW_BUF     4096u         /* 16 KB, ~93 ms -- plenty for a comb */
#define RW_MASK    (RW_BUF - 1u)
#define RW_DENORM  1.0e-18f
#define RW_TWO_PI  6.28318531f

typedef struct RewireState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearPos;
    uint32_t writePos;
    int32_t  decCount;          /* decimator sample-and-hold counter */
    float    decHold;
    float    oscPhase;
    float    lp;
    float    combLp;
    float    shPhase;           /* shifter carrier phase */
    float    imPrev;            /* chain B, delayed one sample */
    float    ap[32];            /* 8 allpass sections x {x1,x2,y1,y2} */
} RewireState;

REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_flush))
static inline float rw_flush(float x)
{
    if (x < RW_DENORM && x > -RW_DENORM) return 0.0f;
    return x;
}

/* Cubic soft clip. Same curve the rest of the pack uses -- no tanh, no math lib. */
REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_soft))
static inline float rw_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

/* Parabolic sine, valid over -pi..pi. Cheaper than a table and needs no array,
 * which matters because static arrays are a freeze class here. */
REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_sin))
static inline float rw_sin(float x)
{
    if (x > 3.14159265f) x -= RW_TWO_PI;
    const float B = 1.27323954f, C = -0.405284735f;
    float y = B * x + C * x * (x < 0.0f ? -x : x);
    return 0.225f * (y * (y < 0.0f ? -y : y) - y) + y;
}

/* ---- the four blocks. static inline: expanded in place, never CALLed ---- */

REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_bits))
static inline float rw_bits(float x, float step, float invStep, int32_t hold,
                            RewireState *st)
{
    /* decimate first, then quantise -- the order inside the block matters as
     * much as the order between blocks, and this is the way a real sample-rate
     * reducer sits in front of a shorter word length. */
    st->decCount++;
    if (st->decCount >= hold) { st->decCount = 0; st->decHold = x; }
    float d = st->decHold;
    float q = d * step;
    int32_t qi = (int32_t)(q + (q >= 0.0f ? 0.5f : -0.5f));
    return (float)qi * invStep;
}

REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_drive))
static inline float rw_drive(float x, float amt)
{
    return rw_soft(x * (1.0f + amt * 14.0f)) * (1.0f - amt * 0.45f);
}

REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_ring))
static inline float rw_ring(float x, float depth, float osc)
{
    return x * (1.0f - depth) + (x * osc) * depth;
}

/* One second-order allpass section, state in s[] as {x1,x2,y1,y2}. Flushed
 * because these poles run up to 0.9985 -- high-Q enough that the tail after
 * silence lands in denormals, which is exactly how Spiral's rise died once.
 *
 * FUNC_ALWAYS_INLINE is load-bearing, not decoration. `static inline` is only a
 * hint: with eight call sites the compiler's code-growth heuristic outlined this
 * into a real CALLed function in .text -- 96 bytes outside .audio, returning via
 * B3 -- which is the same freeze class that killed the first cut of this effect.
 * It compiled without a warning; only the section table showed it. */
REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_ap2))
static inline float rw_ap2(float x, float a, float *s)
{
    float y = a * (x + s[3]) - s[1];
    s[1] = s[0]; s[0] = x;
    s[3] = s[2]; s[2] = rw_flush(y);
    return s[2];
}

/* Single-sideband frequency shift. The allpass chains run whether or not the
 * block is active so their state stays converged and switching in is silent;
 * only the output selection is gated. */
REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_shift))
static inline float rw_shift(float x, float c, float s, int32_t active,
                             RewireState *st)
{
    float *ap = st->ap;

    float re = rw_ap2(x,  RW_HA0, ap +  0);
    re       = rw_ap2(re, RW_HA1, ap +  4);
    re       = rw_ap2(re, RW_HA2, ap +  8);
    re       = rw_ap2(re, RW_HA3, ap + 12);

    float ib = rw_ap2(x,  RW_HB0, ap + 16);
    ib       = rw_ap2(ib, RW_HB1, ap + 20);
    ib       = rw_ap2(ib, RW_HB2, ap + 24);
    ib       = rw_ap2(ib, RW_HB3, ap + 28);

    float im = st->imPrev;
    st->imPrev = ib;

    if (!active) return x;
    return re * c - im * s;
}

REWIRE_EXPAND_PRAGMA(FUNC_ALWAYS_INLINE(rw_comb))
static inline float rw_comb(float x, float depth, float *buf, uint32_t wp,
                            int32_t len, RewireState *st)
{
    uint32_t rp = (wp - (uint32_t)len) & RW_MASK;
    float d = buf[rp];
    st->combLp = rw_flush(st->combLp + 0.35f * (d - st->combLp));
    float y = x + st->combLp * depth * 0.85f;
    buf[wp & RW_MASK] = rw_soft(y);
    return y;
}

void REWIRE_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(RewireState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)RW_BUF * 4u > end) return;

    RewireState *st = (RewireState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != RW_MAGIC || st->version != RW_VERSION || !st->initialized) {
        st->magic = RW_MAGIC;
        st->version = RW_VERSION;
        st->writePos = 0u;
        st->decCount = 0;
        st->decHold = 0.0f;
        st->oscPhase = 0.0f;
        st->lp = 0.0f;
        st->combLp = 0.0f;
        st->shPhase = 0.0f;
        st->imPrev = 0.0f;
        {
            int32_t k;
            for (k = 0; k < 32; k++) st->ap[k] = 0.0f;
        }
        st->clearPos = 0u;
        st->initialized = 1u;
    }

    if (st->clearPos < RW_BUF) {
        uint32_t n = st->clearPos, lim = n + 1024u;
        if (lim > RW_BUF) lim = RW_BUF;
        for (; n < lim; n++) buf[n] = 0.0f;
        st->clearPos = n;
    }

    float rt = zoom_param_norm01(params[REWIRE_ROUTE_SLOT], REWIRE_ROUTE_DEFAULT_NORM);
    float bi = zoom_param_norm01(params[REWIRE_BITS_SLOT],  REWIRE_BITS_DEFAULT_NORM);
    float dr = zoom_param_norm01(params[REWIRE_DRIVE_SLOT], REWIRE_DRIVE_DEFAULT_NORM);
    float rg = zoom_param_norm01(params[REWIRE_RING_SLOT],  REWIRE_RING_DEFAULT_NORM);
    float cb = zoom_param_norm01(params[REWIRE_COMB_SLOT],  REWIRE_COMB_DEFAULT_NORM);
    float sh = zoom_param_norm01(params[REWIRE_SHIFT_SLOT], REWIRE_SHIFT_DEFAULT_NORM);
    float tn = zoom_param_norm01(params[REWIRE_TONE_SLOT],  REWIRE_TONE_DEFAULT_NORM);
    float mx = zoom_param_norm01(params[REWIRE_MIX_SLOT],   REWIRE_MIX_DEFAULT_NORM);

    /* Bits: word length from a literal ladder so 1/step is a literal too, and
     * decimation hold rising with the same knob. */
    float step, invStep;
    if      (bi < 0.17f) { step = 4096.0f; invStep = 2.44140625e-4f; }
    else if (bi < 0.34f) { step = 1024.0f; invStep = 9.765625e-4f; }
    else if (bi < 0.51f) { step =  256.0f; invStep = 3.90625e-3f; }
    else if (bi < 0.68f) { step =   64.0f; invStep = 1.5625e-2f; }
    else if (bi < 0.85f) { step =   24.0f; invStep = 4.1666667e-2f; }
    else                 { step =    8.0f; invStep = 0.125f; }
    int32_t hold = 1 + (int32_t)(bi * bi * 23.0f);       /* 1 .. 24 samples */

    /* Ring: the knob is carrier frequency, and depth fades in from silence at 0
     * so the block is genuinely absent rather than quietly detuning things. */
    float carrier = 30.0f + rg * rg * 2200.0f;
    float oscInc = carrier * (RW_TWO_PI / 44100.0f);
    float ringDepth = rg < 0.03f ? 0.0f : (rg - 0.03f) * 1.03f;

    int32_t combLen = 24 + (int32_t)(cb * 900.0f);
    float combDepth = cb;

    float lpCoef = 0.03f + tn * 0.6f;

    /* Shift: centre-off, squared taper so the first few Hz either side of centre
     * are actually reachable -- a 2 Hz shift is a slow through-zero phase drift
     * and musically the most useful part of the range. */
    float sd = (sh - 0.5f) * 2.0f;                            /* -1 .. +1 */
    float shHz = sd * (sd < 0.0f ? -sd : sd) * RW_MAX_SHIFT;  /* signed square */
    int32_t shActive = (shHz > 0.35f || shHz < -0.35f) ? 1 : 0;
    float shInc = shHz * (RW_TWO_PI / 44100.0f);

    /* Route: five orders. if/else, never switch. */
    /* Order packed one nibble per stage: 0=Bits 1=Drive 2=Ring 3=Comb 4=Shift. */
    int32_t packed;
    if      (rt < 0.20f) packed = 0x01234;   /* B D R C S */
    else if (rt < 0.40f) packed = 0x43210;   /* S C R D B */
    else if (rt < 0.60f) packed = 0x14032;   /* D S B C R */
    else if (rt < 0.80f) packed = 0x23401;   /* R C S B D */
    else                 packed = 0x40213;   /* S B R D C */

    uint32_t wp = st->writePos;
    float ph = st->oscPhase;
    float shPh = st->shPhase;
    float lp = st->lp;

    int i;
    for (i = 0; i < 8; i++) {
        float dry = 0.5f * (fxBuf[i] + fxBuf[i + 8]);

        ph += oscInc;
        if (ph > RW_TWO_PI) ph -= RW_TWO_PI;
        float osc = rw_sin(ph);

        /* Shifter carrier. Wrapped both ways because shInc goes negative for a
         * downward shift. cos comes from the same parabolic sine a quarter turn
         * along; shPh stays under 2*pi so one wrap inside rw_sin is enough. */
        shPh += shInc;
        if (shPh > RW_TWO_PI) shPh -= RW_TWO_PI;
        if (shPh < 0.0f)      shPh += RW_TWO_PI;
        float shCos = rw_sin(shPh + RW_HALF_PI);
        float shSin = rw_sin(shPh);

        /* Apply the four blocks in the order this route packs. Each block
         * appears ONCE in the source and the stage loop picks between them.
         *
         * The first cut wrote five straight-line arms with all four blocks
         * expanded inside each -- twenty expansions -- and the compiler stopped
         * inlining, emitting 256 bytes of .text outside the .audio section and
         * twelve relocations with it. Both are freeze classes here. Packing the
         * order into a nibble field costs a shift and keeps every block inline. */
        int32_t stage;
        float x = dry;
        #pragma UNROLL(1)
        for (stage = 0; stage < 5; stage++) {
            int32_t which = (packed >> (16 - stage * 4)) & 0xF;
            if      (which == 0) x = rw_bits(x, step, invStep, hold, st);
            else if (which == 1) x = rw_drive(x, dr);
            else if (which == 2) x = rw_ring(x, ringDepth, osc);
            else if (which == 3) x = rw_comb(x, combDepth, buf, wp, combLen, st);
            else                 x = rw_shift(x, shCos, shSin, shActive, st);
        }
        wp++;

        lp += lpCoef * (x - lp);
        float wet = lp;

        float out = dry * (1.0f - mx) + rw_soft(wet) * mx;
        fxBuf[i]     = out;
        fxBuf[i + 8] = out;
    }

    st->writePos = wp;
    st->oscPhase = ph;
    st->shPhase = shPh;
    st->lp = rw_flush(lp);
}
