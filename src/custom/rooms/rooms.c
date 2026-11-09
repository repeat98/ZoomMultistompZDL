/*
 * rooms.c -- Rooms: a Death By Audio Rooms-inspired multi-mode reverb, MS-70CDR.
 *
 * One reverb core (Freeverb-style: 6 damped comb filters in parallel -> 3 series
 * allpass diffusers) feeds six selectable "room" characters. TIME is the global
 * decay; FREQ and DEPTH are reinterpreted per mode; MIX blends dry/wet.
 *
 * 5 knobs:
 *   Mode  (params[5]) - 0 ROOM · 1 DIGIT · 2 PEAK · 3 GATE · 4 WAVE · 5 GONG
 *   Time  (params[6]) - reverb decay (all modes)
 *   Freq  (params[7]) - per-mode: damping / crush-rate / filter freq /
 *                       gate-time / LFO rate / gong pitch
 *   Depth (params[8]) - per-mode: size / bit-depth / resonance / threshold /
 *                       mod-depth / regen
 *   Mix   (params[9]) - dry/wet
 *
 * SAFE-DSP (docs/SAFE-DSP-RULES.md):
 *   - NO `switch` and no dense int if/else: the mode is selected BRANCHLESSLY
 *     with float compares (en = (mode==k)?1:0), which are predicated selects,
 *     not a jump table. (A jump table's indirect branch is unrelocated here and
 *     freezes the DSP -- it was Mangle's freeze bug.)
 *   - Reverb reads are all at FIXED distances; the only moving read (WAVE) is
 *     feed-FORWARD (never fed back). Both patterns are hardware-proven.
 *   - No static/const arrays: the comb/allpass tunings live in the ctx[3] state
 *     (RAM), initialised from scalar literals.
 *   - No runtime divide (ring wrap is compare+reset, crush inverse is built in
 *     the IEEE exponent field), no modulo, no float->unsigned cast, no math lib
 *     (polynomial sine). Feedback is soft-clipped and denormals are flushed, so
 *     even self-oscillating modes stay bounded and never stall the FPU.
 *   ctx[11]/ctx[12] magic shuttle preserved; ctx[3] arena validated + cleared.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "rooms_params.h"

#ifndef ROOMS_AUDIO_FUNC
#define ROOMS_AUDIO_FUNC Fx_REV_Rooms
#endif

#define ROOMS_DO_PRAGMA(x) _Pragma(#x)
#define ROOMS_EXPAND_PRAGMA(x) ROOMS_DO_PRAGMA(x)
#define ROOMS_CODE_SECTION(f) ROOMS_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

ROOMS_CODE_SECTION(ROOMS_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define RM_MAGIC   0x524F4F4Du        /* 'ROOM' */
#define RM_VERSION 1u

/* Freeverb-derived comb + allpass tunings (44.1 kHz), and their cumulative
 * offsets into one contiguous float buffer. */
#define RM_C0 1116u
#define RM_C1 1188u
#define RM_C2 1277u
#define RM_C3 1356u
#define RM_C4 1422u
#define RM_C5 1491u
#define RM_A0 556u
#define RM_A1 441u
#define RM_A2 341u
#define RM_WAVE 2048u                 /* WAVE mod-delay ring */

#define RM_O0 0u
#define RM_O1 (RM_O0 + RM_C0)
#define RM_O2 (RM_O1 + RM_C1)
#define RM_O3 (RM_O2 + RM_C2)
#define RM_O4 (RM_O3 + RM_C3)
#define RM_O5 (RM_O4 + RM_C4)
#define RM_OA0 (RM_O5 + RM_C5)
#define RM_OA1 (RM_OA0 + RM_A0)
#define RM_OA2 (RM_OA1 + RM_A1)
#define RM_OWAVE (RM_OA2 + RM_A2)
#define RM_TOTAL (RM_OWAVE + RM_WAVE)

#define RM_CLEAR_STEP 4096u
#define RM_INGAIN     0.040f
#define RM_TWO_PI     6.2831853f
#define RM_WAVE_MASKF 2047.0f

typedef struct RoomsState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    uint32_t combOff[6], combLen[6], combPos[6];
    float    combLp[6];              /* damping low-pass state per comb */
    uint32_t allOff[3], allLen[3], allPos[3];

    uint32_t wavePos;                /* WAVE mod-delay write head */
    float    lfo;                    /* WAVE LFO phase */
    float    svfLp, svfBp;           /* PEAK/GONG state-variable filter */
    float    gateEnv;                /* GATE envelope follower */
    float    shReg;                  /* DIGIT sample-hold register */
    uint32_t shCnt;                  /* DIGIT sample-hold counter */
    uint32_t fpd;                    /* anti-denormal dither */
} RoomsState;

static inline float rm_abs(float x) { return x < 0.0f ? -x : x; }

static inline float rm_sin(float x)
{
    const float twoPi = 6.28318530718f, pi = 3.14159265359f, inv = 0.15915494309f;
    x = x - twoPi * (float)((int)(x * inv));
    if (x < -pi) x += twoPi;
    if (x > pi) x -= twoPi;
    float y = 1.2732395447f * x - 0.4052847346f * x * rm_abs(x);
    return y + 0.225f * (y * rm_abs(y) - y);
}

/* unity-slope soft clip (safe in feedback loops) */
static inline float rm_soft(float x)
{
    if (x > 1.5f) return 1.0f;
    if (x < -1.5f) return -1.0f;
    return x - (x * x * x) * 0.14814815f;
}

/* 2^bits and 2^-bits WITHOUT a switch (jump table = freeze) or divide. */
static inline void rm_crush_scale(int bits, float *mul, float *inv)
{
    if (bits < 3) bits = 3; else if (bits > 8) bits = 8;
    *mul = (float)(1 << bits);
    union { uint32_t u; float f; } cvt;
    cvt.u = ((uint32_t)(127 - bits)) << 23;
    *inv = cvt.f;
}

void ROOMS_AUDIO_FUNC(unsigned int *ctx)
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

    uintptr_t bufBase = (base + sizeof(RoomsState) + 7u) & ~(uintptr_t)7u;
    if (bufBase + (uintptr_t)RM_TOTAL * 4u > end) return;

    RoomsState *st = (RoomsState *)base;
    float *buf = (float *)bufBase;

    if (st->magic != RM_MAGIC || st->version != RM_VERSION) {
        st->magic = RM_MAGIC;
        st->version = RM_VERSION;
        st->initialized = 0u;
        st->clearIndex = 0u;
        st->combOff[0]=RM_O0; st->combOff[1]=RM_O1; st->combOff[2]=RM_O2;
        st->combOff[3]=RM_O3; st->combOff[4]=RM_O4; st->combOff[5]=RM_O5;
        st->combLen[0]=RM_C0; st->combLen[1]=RM_C1; st->combLen[2]=RM_C2;
        st->combLen[3]=RM_C3; st->combLen[4]=RM_C4; st->combLen[5]=RM_C5;
        st->allOff[0]=RM_OA0; st->allOff[1]=RM_OA1; st->allOff[2]=RM_OA2;
        st->allLen[0]=RM_A0;  st->allLen[1]=RM_A1;  st->allLen[2]=RM_A2;
        for (int i=0;i<6;i++){ st->combPos[i]=0u; st->combLp[i]=0.0f; }
        for (int i=0;i<3;i++) st->allPos[i]=0u;
        st->wavePos=0u; st->lfo=0.0f; st->svfLp=0.0f; st->svfBp=0.0f;
        st->gateEnv=0.0f; st->shReg=0.0f; st->shCnt=0u; st->fpd=0x2468ACE1u;
    }
    if (st->fpd == 0u) st->fpd = 0x2468ACE1u;

    if (!st->initialized) {
        uint32_t e = st->clearIndex + RM_CLEAR_STEP;
        if (e > RM_TOTAL) e = RM_TOTAL;
        for (uint32_t i = st->clearIndex; i < e; i++) buf[i] = 0.0f;
        st->clearIndex = e;
        if (e >= RM_TOTAL) st->initialized = 1u;
        return;
    }

    float modeN = zoom_param_norm01(params[ROOMS_MODE_SLOT],  ROOMS_MODE_DEFAULT_NORM);
    float timeN = zoom_param_norm01(params[ROOMS_TIME_SLOT],  ROOMS_TIME_DEFAULT_NORM);
    float freq  = zoom_param_norm01(params[ROOMS_FREQ_SLOT],  ROOMS_FREQ_DEFAULT_NORM);
    float depth = zoom_param_norm01(params[ROOMS_DEPTH_SLOT], ROOMS_DEPTH_DEFAULT_NORM);
    float mix   = zoom_param_norm01(params[ROOMS_MIX_SLOT],   ROOMS_MIX_DEFAULT_NORM);

#ifdef ROOMS_DISCRETE_MODE
    /* Separate Rooms6 patch ID: shared edit handler stores raw UI / 100. */
    int mode = (int)(modeN * 100.0f + 0.5f);
#else
    int mode = (int)(modeN * 5.999f);
#endif
    if (mode < 0) mode = 0; else if (mode > 5) mode = 5;
    /* branchless mode enables (predicated compares, never a jump table) */
    float enRoom  = (mode==0)?1.0f:0.0f;
    float enDigit = (mode==1)?1.0f:0.0f;
    float enPeak  = (mode==2)?1.0f:0.0f;
    float enGate  = (mode==3)?1.0f:0.0f;
    float enWave  = (mode==4)?1.0f:0.0f;
    float enGong  = (mode==5)?1.0f:0.0f;

    float wetMix = mix, dry = 1.0f - mix;

    /* --- global decay; GONG's depth pushes it toward self-oscillation --- */
    /* Time -> decay, geometric rather than linear in fb.
     *
     * fb used to be a straight lerp 0.70..0.983. Because T60 goes as
     * 1/ln(fb), that put 0.65s..2.5s across the FIRST THREE QUARTERS of the
     * knob and 2.5s..13.6s in the last quarter -- so most of the travel did
     * almost nothing and the knob read as dead. Making (1 - fb) geometric
     * instead gives an even ~1.33x per 10 clicks: 0.65, 0.90, 1.23 ... 12.1 s.
     *
     * (1 - fb) = 0.30 * exp(-2.744 * timeN), and exp() is a helper call, so it
     * is evaluated as (exp(-0.343*t))^8 -- a cubic Taylor term small enough to
     * be accurate at u <= 0.343, then three squarings. Multiplies only; max
     * error vs a true exp is 1.2e-4 in fb. */
    float u = 0.343f * timeN;
    float e = 1.0f - u + 0.5f * u * u - 0.16666667f * u * u * u;
    e = e * e; e = e * e; e = e * e;                   /* ^8 */
    float fb = 1.0f - 0.30f * e;                       /* 0.70 .. ~0.981 */
    fb += enGong * depth * (0.997f - fb);              /* GONG regen -> up to ~0.997 */

    /* --- damping: ROOM uses FREQ; other modes a fixed moderate value --- */
    float damp = 0.35f;
    damp += enRoom * ((0.05f + 0.9f * freq) - damp);   /* ROOM: bright..dark */
    float dampInv = 1.0f - damp;

    /* --- ROOM size, from DEPTH ---
     *
     * Depth is documented at the top of this file as per-mode, with "size" as its
     * job in ROOM. Every other mode used it -- DIGIT for bit depth, PEAK for
     * resonance, GATE for threshold, WAVE for mod depth, GONG for regen -- and
     * ROOM alone never read it, so at Mode 0, which is the DEFAULT, the knob did
     * nothing at all. Emulator sweeps put the output bit-identical across the
     * whole travel at Mode 0 and clearly moving at all five others.
     *
     * Size scales the comb tunings. Shortening the delays packs the echo density
     * tighter and raises the modal pitch, which is what a smaller room does; the
     * Freeverb tunings stay the ratio they are so it stays coherent rather than
     * turning metallic. Only ever a FRACTION of the allocated span, never more,
     * so the reads stay inside the buffer that was sized for full length.
     * Other modes are pinned at 1.0 and behave exactly as before. */
    float sizeN = 1.0f;
    sizeN += enRoom * ((0.45f + 0.55f * depth) - sizeN);   /* ROOM: 0.45 .. 1.0 */

    /* --- DIGIT crush params (from FREQ = rate, DEPTH = bit depth) --- */
    uint32_t srN = 1u + (uint32_t)(int)(freq * 24.0f);
    int bits = 8 - (int)(depth * 5.0f);
    float cMul = 256.0f, cInv = 0.00390625f;
    rm_crush_scale(bits, &cMul, &cInv);

    /* --- PEAK/GONG state-variable filter coeffs --- */
    float fc = 80.0f + freq * freq * 6000.0f;          /* PEAK sweep */
    fc += enGong * ((300.0f + freq * 2500.0f) - fc);   /* GONG metallic band */
    float svf_f = 2.0f * rm_sin(fc * 7.1237935e-5f);   /* fc * (pi/44100), no divide */
    if (svf_f > 1.6f) svf_f = 1.6f; else if (svf_f < 0.003f) svf_f = 0.003f;
    float svf_q = 2.0f - depth * 1.98f;                /* high depth -> resonance */
    float peakBoost = 1.0f + depth * 6.0f;

    /* --- GATE params (FREQ = release/hold, DEPTH = threshold) --- */
    float gateRel = 0.9990f - freq * 0.02f;            /* slower release when low */
    float gateThr = 0.004f + depth * 0.25f;

    /* --- WAVE params (FREQ = LFO rate, DEPTH = mod depth) --- */
    float lfoInc = (0.2f + freq * 8.0f) * (RM_TWO_PI / 44100.0f);
    float modAmt = depth * 380.0f;
    float waveBase = 600.0f;

    uint32_t fpd = st->fpd;

    int f;
    for (f = 0; f < 8; f++) {
        float inL = fxBuf[f];
        float inR = fxBuf[f + 8];
        float in = 0.5f * (inL + inR);

        /* bipolar sub-audible dither keeps the reverb tail above denormals */
        fpd ^= fpd << 13; fpd ^= fpd >> 17; fpd ^= fpd << 5;
        float dz = ((float)(int)(fpd & 0xFFFFu) - 32768.0f) * 3.0e-18f;
        float fin = in * RM_INGAIN + dz;

        /* ---- 6 parallel damped combs ---- */
        float combSum = 0.0f;
        for (int c = 0; c < 6; c++) {
            uint32_t idx = st->combOff[c] + st->combPos[c];
            float y = buf[idx];
            float lp = st->combLp[c] * damp + y * dampInv;
            st->combLp[c] = lp;
            /* linear feedback (Freeverb gain structure); fb < 1 keeps it stable,
             * the input dither keeps it out of denormals -- no per-comb clip so
             * the combs sum to a full-level reverb. */
            buf[idx] = fin + lp * fb;
            /* Effective length is the tuning scaled by ROOM's size; clamped low so
             * a small room cannot collapse a comb into a buzzing few samples, and
             * it never exceeds combLen so it stays inside the allocated span. */
            uint32_t clen = (uint32_t)(int)((float)(int)st->combLen[c] * sizeN);
            if (clen < 160u) clen = 160u;
            if (clen > st->combLen[c]) clen = st->combLen[c];
            uint32_t p = st->combPos[c] + 1u;
            if (p >= clen) p = 0u;
            st->combPos[c] = p;
            combSum += y;
        }

        /* ---- 3 series allpass diffusers ---- */
        float x = combSum;
        for (int a = 0; a < 3; a++) {
            uint32_t idx = st->allOff[a] + st->allPos[a];
            float bv = buf[idx];
            float out = bv - x;
            buf[idx] = x + bv * 0.5f;
            uint32_t p = st->allPos[a] + 1u;
            if (p >= st->allLen[a]) p = 0u;
            st->allPos[a] = p;
            x = out;
        }
        float wet = x;                                 /* raw reverb (ROOM) */

        /* ---- DIGIT: sample-rate reduce + bitcrush ---- */
        st->shCnt++;
        if (st->shCnt >= srN) { st->shReg = wet; st->shCnt = 0u; }
        float sh = st->shReg;
        float wDigit = (float)((int)(sh * cMul + (sh >= 0.0f ? 0.5f : -0.5f))) * cInv;

        /* ---- PEAK/GONG: resonant state-variable filter ---- */
        float lpS = st->svfLp + svf_f * st->svfBp;
        float hpS = wet - lpS - svf_q * st->svfBp;
        float bpS = st->svfBp + svf_f * hpS;
        if (lpS > -1.0e-25f && lpS < 1.0e-25f) lpS = 0.0f;
        if (bpS > -1.0e-25f && bpS < 1.0e-25f) bpS = 0.0f;
        st->svfLp = lpS; st->svfBp = bpS;
        float wPeak = rm_soft(bpS * peakBoost);

        /* ---- GATE: envelope-follower gate ---- */
        float aw = rm_abs(wet);
        float env = st->gateEnv;
        env = (aw > env) ? aw : (env * gateRel);
        st->gateEnv = env;
        float g = (env - gateThr) * 12.0f;
        if (g < 0.0f) g = 0.0f; else if (g > 1.0f) g = 1.0f;
        float wGate = wet * g;

        /* ---- WAVE: feed-forward modulated delay on the wet ---- */
        buf[RM_OWAVE + st->wavePos] = wet;
        float d = waveBase + modAmt * (0.5f + 0.5f * rm_sin(st->lfo));
        st->lfo += lfoInc;
        if (st->lfo > RM_TWO_PI) st->lfo -= RM_TWO_PI;
        int di = (int)d;
        float fr = d - (float)di;
        int r0 = (int)st->wavePos - di; if (r0 < 0) r0 += (int)RM_WAVE;
        int r1 = r0 - 1; if (r1 < 0) r1 += (int)RM_WAVE;
        float wWave = buf[RM_OWAVE + r0] * (1.0f - fr) + buf[RM_OWAVE + r1] * fr;
        uint32_t wp = st->wavePos + 1u;
        if (wp >= RM_WAVE) wp = 0u;
        st->wavePos = wp;

        /* ---- GONG: resonant filter path, longer/metallic ---- */
        float wGong = rm_soft(bpS * (peakBoost * 0.7f) + wet * 0.5f);

        /* ---- branchless mode select ---- */
        float character = enRoom  * wet
                        + enDigit * wDigit
                        + enPeak  * wPeak
                        + enGate  * wGate
                        + enWave  * wWave
                        + enGong  * wGong;

        /* one soft-clip on the wet output bounds the self-oscillating modes */
        float wc = rm_soft(character);
        fxBuf[f]     = dry * inL + wetMix * wc;
        fxBuf[f + 8] = dry * inR + wetMix * wc;
    }

    st->fpd = fpd;
}
