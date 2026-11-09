/*
 * totape9_zoom.c
 *
 * ToTape9 by Chris Johnson (airwindows) – MIT licence
 * Experimental TI TMS320C674x / Zoom Multistomp build.
 *
 * Release status
 * --------------
 * This is the first ctx[3]-backed ToTape9 full-kernel attempt. Persistent DSP
 * state lives in the per-instance host descriptor arena proven by StereoChorus,
 * not in .fardata.
 *
 * Assumptions
 * -----------
 *  - Sample rate is 44100 Hz  →  overallscale = 1.0, spacing = 1, slewsing = 2
 *    Only the avg2 stage of TapeHack2 is active; avg4/8/16/32 stages are dead code
 *    at this sample rate and are omitted entirely.
 *  - The Zoom firmware calls this function with a pointer to a context structure
 *    in register A4 (first argument by C674x calling convention).
 *  - Knobs are on three pages, three knobs each (IDs 2-10):
 *
 *    Page 1  ID2 = Input     A3[5]   0-1  → gain 0-4×
 *            ID3 = Tilt      A3[6]   0-1  → dubly encode/decode amount
 *            ID4 = Shape     A3[7]   0-1  → IIR frequency for dubly
 *    Page 2  ID5 = Flutter   A3[8]   0-1  → tape flutter depth
 *            ID6 = FlutSpd   A3[9]   0-1  → flutter LFO speed
 *            ID7 = Bias      A3[10]  0-1  → tape bias (0=dark, 0.5=neutral, 1=bright)
 *    Page 3  ID8 = HeadBump  A3[11]  0-1  → head-bump resonance amount
 *            ID9 = Output    A3[12]  0-1  → wet output trim 0-2×
 *            ID10= Mix       A3[13]  0-1  → dry/wet crossfade
 *
 *    A3[0]  = on/off multiplier (1.0 when on, 0.0 when off)
 *    A3[4]  = knob level multiplier  (so knob value 100 → 1.0)
 *
 * Build (TI Code Composer Studio, Generic C674x device, compiler 8.3.x, Release)
 * -------------------------------------------------------------------------------
 *   cl6x -o3 -mv6740 --abi=eabi --mem_model:data=far \
 *         -c totape9_zoom.c -o totape9_zoom.obj
 *   dis6x totape9_zoom.obj totape9_zoom_dis.asm
 *   python3 totape9/apply_relocs.py          → produces totape9/TOTAPE9.ZDL
 *
 *   NOTE: --mem_model:data=far is REQUIRED.  Without it the compiler places
 *   small static variables in .bss and accesses them via B14-relative (SBR)
 *   addressing.  The Zoom firmware does not set B14 to a valid address before
 *   calling .audio, so all state accesses would hit garbage memory.
 *   With --mem_model:data=far every variable goes into a .far:* section and
 *   is addressed with an absolute MVKL/MVKH pair – safe and linker-independent.
 */

/* #include <math.h>  -- replaced with inline implementations below */
#include <stdint.h>

#include "../common/zoom_params.h"
#include "../common/tape_controls.h"
#include "totape9_params.h"

#define TOTAPE9_PERSISTENT_STATE 1
#ifndef TOTAPE9_FULL_DSP
#define TOTAPE9_FULL_DSP 1
#endif

#ifndef TOTAPE9_AUDIO_FUNC
#define TOTAPE9_AUDIO_FUNC Fx_DRV_ToTape9
#endif

#if TOTAPE9_FULL_DSP
/* =========================================================================
 * Inline math functions
 *
 * The Zoom ZDL runtime does not provide sinf/logf/tanf.  No stock Zoom
 * effect uses them, so they are not in the firmware's RTS.  We provide
 * lightweight inline versions here so the compiler folds them into the
 * .audio section and no external symbol reference is generated.
 *
 * __c6xabi_divf (float divide) can be linked, but hardware has repeatedly
 * shown helper-heavy DSP paths are fragile. Keep runtime math multiply-only
 * unless a specific helper call has been isolated and hardware-tested.
 *
 * Accuracy targets:  ~20-bit mantissa (sufficient for audio, IEEE single
 * has 24-bit mantissa).  These are NOT fully IEEE-754 compliant – no
 * special-case handling for NaN/Inf/denormals.
 * ====================================================================== */

static inline float recip_approx_pos(float x)
{
    union { float f; uint32_t u; } conv;
    conv.f = x;
    conv.u = 0x7EF311C3u - conv.u;
    float y = conv.f;
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    return y;
}

/* --- sinf: no-divide polynomial approximation ------------------------ */
static inline float zoom_sinf(float x)
{
    const float TWO_PI  = 6.2831853f;
    const float PI      = 3.1415927f;
    const float INV_2PI = 0.15915494f;

    x = x - TWO_PI * (float)(int)(x * INV_2PI);
    if (x < 0.0f) x += TWO_PI;
    float sign = 1.0f;
    if (x > PI) { x -= PI; sign = -1.0f; }
    if (x > 1.5707963f) x = PI - x;

    float x2 = x * x;
    float p = x;
    p -= x * x2 * 0.16666667f;
    x *= x2;
    p += x * x2 * 0.0083333310f;
    x *= x2;
    p -= x * x2 * 0.0001984090f;
    return sign * p;
}

/* --- logf: bit-hack + polynomial correction -------------------------- */
static inline float zoom_logf(float x)
{
    /* Fast log2 via IEEE 754 float bit layout + correction polynomial.
       log(x) = log2(x) * ln(2) */
    union { float f; uint32_t u; } conv;
    conv.f = x;
    /* Extract exponent and mantissa */
    int exp = (int)((conv.u >> 23) & 0xFF) - 127;
    conv.u = (conv.u & 0x007FFFFFu) | 0x3F800000u;  /* m in [1, 2) */
    float m = conv.f;

    /* Minimax polynomial for log2(m) over [1, 2), ~20-bit accuracy */
    float log2_m = -1.7417939f + m * (2.8212026f + m * (-1.4699568f + m * 0.44717955f));

    /* log(x) = (exp + log2_m) * ln(2) */
    return ((float)exp + log2_m) * 0.6931472f;
}

/* --- tanf: small-angle polynomial for ToTape9 head-bump frequencies --- */
static inline float zoom_tanf(float x)
{
    float x2 = x * x;
    return x + x * x2 * 0.33333334f + x * x2 * x2 * 0.13333334f;
}

/* Redirect standard names */
#define sinf(x) zoom_sinf(x)
#define logf(x) zoom_logf(x)
#define tanf(x) zoom_tanf(x)
#endif

#define TOTAPE9_DO_PRAGMA(x) _Pragma(#x)
#define TOTAPE9_EXPAND_PRAGMA(x) TOTAPE9_DO_PRAGMA(x)
#define TOTAPE9_CODE_SECTION(func) TOTAPE9_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))
TOTAPE9_CODE_SECTION(TOTAPE9_AUDIO_FUNC)

/*
 * On the TI C674x (32-bit target) sizeof(unsigned int) == sizeof(void*) == 4,
 * so the pointer casts below are correct.  On a 64-bit host (used only for
 * syntax-checking) the compiler will warn; those warnings are expected and safe
 * to ignore.
 */
/* By-ear level match against the rest of the pack: tape saturation lifts RMS,
 * so the wet path needs trimming before it is crossfaded in. */
#define TOTAPE9_WET_TRIM 0.7f

#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* -------------------------------------------------------------------------
 * Constants
 * ---------------------------------------------------------------------- */

#ifndef FLUTTER_BUF
#define FLUTTER_BUF  1002
#endif
#define PHI          1.6180339887498948f
#define KNOB_NORM    (1.0f / 0.14f)

#define TOTAPE9_MAGIC 0x54395039u
#define TOTAPE9_VERSION 5u

/* -------------------------------------------------------------------------
 * gslew layout: 9 stages × 3 words = [prevL, prevR, threshold]  (27 words)
 * ---------------------------------------------------------------------- */
#define GSLEW_TOTAL  27

/* -------------------------------------------------------------------------
 * Head-bump biquad field indices  (hdb_total = 11)
 * ---------------------------------------------------------------------- */
#define HDB_FREQ  0
#define HDB_RESO  1
#define HDB_A0    2
#define HDB_A1    3
#define HDB_A2    4
#define HDB_B1    5
#define HDB_B2    6
#define HDB_SL1   7
#define HDB_SL2   8
#define HDB_SR1   9
#define HDB_SR2   10
#define HDB_TOTAL 11

/* =========================================================================
 * Persistent state (single-instance)
 * ====================================================================== */

#define TOTAPE9_CLEAR_STEP 32u

typedef struct ToTape9State {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;
    uint32_t criticalParamCacheReady;
    float cachedInput;
    float cachedBias;
    float cachedOutput;

    float iirEncL, iirEncR;
    float compEncL, compEncR;
    float avgEncL, avgEncR;

    float iirDecL, iirDecR;
    float compDecL, compDecR;
    float avgDecL, avgDecR;

    float dL[FLUTTER_BUF];
    float dR[FLUTTER_BUF];
    float sweepL;
    float sweepR;
    float nextmaxL;
    float nextmaxR;
    int gcount;

    float gslew[GSLEW_TOTAL];
    float hysteresisL, hysteresisR;

    float avg2L[2], avg2R[2];
    float post2L[2], post2R[2];
    int avgPos;
    float lastDarkL, lastDarkR;

    float headBumpL, headBumpR;
    float hdbA[HDB_TOTAL], hdbB[HDB_TOTAL];

    float lastSampL, lastSampR;
    float intermedL, intermedR;
    float slewArrL[2], slewArrR[2];
    int wasPosClipL, wasNegClipL;
    int wasPosClipR, wasNegClipR;

    uint32_t fpdL;
    uint32_t fpdR;
} ToTape9State;

static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

#define TOTAPE9_PARAM_MISSING(raw) (!((raw) >= 0.0f && (raw) <= 100.0f))
#define TOTAPE9_PARAM_NORM(raw, fallback_norm) zoom_param_norm01((raw), (fallback_norm))

static inline void start_lazy_init(ToTape9State *st)
{
    /* Stamp the header so future callbacks see "init in progress". The full
     * state zero is split across multiple callbacks to match the proven
     * StereoChorus shape. T9InitOnly later confirmed this lazy ctx[3] init
     * completes cleanly; the remaining ToTape9 lifecycle risk is parameter
     * materialization on reload, not this state path. */
    st->magic = TOTAPE9_MAGIC;
    st->version = TOTAPE9_VERSION;
    st->initialized = 0u;
    st->clearIndex = 32u;  /* skip the header/cache words just written */
    st->criticalParamCacheReady = 1u;
    st->cachedInput = TOTAPE9_INPUT_DEFAULT_NORM;
    st->cachedBias = TOTAPE9_BIAS_DEFAULT_NORM;
    st->cachedOutput = TOTAPE9_MIX_DEFAULT_NORM;
}

static inline void clear_state_chunk(ToTape9State *st)
{
    /* Word-aligned stores. clearIndex starts after the header/cache words and advances by
     * TOTAPE9_CLEAR_STEP (both multiples of 4), so the cast is safe.
     * Stock effects use word stores, and cl6x emits cleaner pipelined
     * STW for this form than for byte-clearing a large state struct. */
    uint32_t *w = (uint32_t *)(void *)st;
    uint32_t startWord = st->clearIndex >> 2;
    uint32_t endWord = startWord + (TOTAPE9_CLEAR_STEP >> 2);
    uint32_t totalWords = (uint32_t)(sizeof(ToTape9State) >> 2);
    if (endWord > totalWords) endWord = totalWords;
    uint32_t i;
    for (i = startWord; i < endWord; i++) {
        w[i] = 0u;
    }
    st->clearIndex = endWord << 2;
    if (endWord >= totalWords) {
        st->compEncL = 1.0f;
        st->compEncR = 1.0f;
        st->compDecL = 1.0f;
        st->compDecR = 1.0f;
        st->sweepL = 3.14159265359f;
        st->sweepR = 3.14159265359f;
        st->nextmaxL = 0.5f;
        st->nextmaxR = 0.5f;
        st->fpdL = 0x1234567u;
        st->fpdR = 0x89ABCDFu;
        st->criticalParamCacheReady = 1u;
        st->cachedInput = TOTAPE9_INPUT_DEFAULT_NORM;
        st->cachedBias = TOTAPE9_BIAS_DEFAULT_NORM;
        st->cachedOutput = TOTAPE9_MIX_DEFAULT_NORM;
        st->initialized = 1u;
    }
}

#define iirEncL (st->iirEncL)
#define iirEncR (st->iirEncR)
#define compEncL (st->compEncL)
#define compEncR (st->compEncR)
#define avgEncL (st->avgEncL)
#define avgEncR (st->avgEncR)
#define iirDecL (st->iirDecL)
#define iirDecR (st->iirDecR)
#define compDecL (st->compDecL)
#define compDecR (st->compDecR)
#define avgDecL (st->avgDecL)
#define avgDecR (st->avgDecR)
#define dL (st->dL)
#define dR (st->dR)
#define sweepL (st->sweepL)
#define sweepR (st->sweepR)
#define nextmaxL (st->nextmaxL)
#define nextmaxR (st->nextmaxR)
#define gcount (st->gcount)
#define gslew (st->gslew)
#define hysteresisL (st->hysteresisL)
#define hysteresisR (st->hysteresisR)
#define avg2L (st->avg2L)
#define avg2R (st->avg2R)
#define post2L (st->post2L)
#define post2R (st->post2R)
#define avgPos (st->avgPos)
#define lastDarkL (st->lastDarkL)
#define lastDarkR (st->lastDarkR)
#define headBumpL (st->headBumpL)
#define headBumpR (st->headBumpR)
#define hdbA (st->hdbA)
#define hdbB (st->hdbB)
#define lastSampL (st->lastSampL)
#define lastSampR (st->lastSampR)
#define intermedL (st->intermedL)
#define intermedR (st->intermedR)
#define slewArrL (st->slewArrL)
#define slewArrR (st->slewArrR)
#define wasPosClipL (st->wasPosClipL)
#define wasNegClipL (st->wasNegClipL)
#define wasPosClipR (st->wasPosClipR)
#define wasNegClipR (st->wasNegClipR)

/* =========================================================================
 * Head-bump biquad coefficient calculation
 * ====================================================================== */

#if TOTAPE9_FULL_DSP
static inline void computeHDB(float *hdb, float normalizedFreq, float reso)
{
    hdb[HDB_FREQ] = normalizedFreq;
    hdb[HDB_RESO] = reso;
    hdb[HDB_A1]   = 0.0f;
    float K = tanf(3.14159265358979323f * normalizedFreq);
    float invReso = recip_approx_pos(reso);
    float KOverReso = K * invReso;
    float KK = K * K;
    float norm = recip_approx_pos(1.0f + KOverReso + KK);
    hdb[HDB_A0] =  KOverReso * norm;
    hdb[HDB_A2] = -hdb[HDB_A0];
    hdb[HDB_B1] =  2.0f * (KK - 1.0f) * norm;
    hdb[HDB_B2] =  (1.0f - KOverReso + KK) * norm;
}
#endif

/* =========================================================================
 * Main entry point
 *
 * ctx layout (words, matching existing Zoom .audio asm):
 *   ctx[1]  – parameter structure pointer
 *   ctx[4]  – Dry buffer pointer
 *   ctx[5]  – Fx  buffer pointer
 *   ctx[11] – magic destination (indirected, write once)
 *   ctx[12] – magic source      (read once per loop iteration)
 * ====================================================================== */

void TOTAPE9_AUDIO_FUNC(unsigned int *ctx)
{
#if !TOTAPE9_FULL_DSP
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    /* Small-stack release core. The full Airwindows body below is kept for
     * future state-ABI work, but this path avoids the large state block that
     * freezes hardware while preserving the source parameter control laws.
     *
     * These read through zoom_param_norm01, NOT zoom_param_norm. The latter
     * multiplies by 1/0.14, which pins every knob to its maximum above ~14% of
     * travel -- so Input leapt to full gain around 15 and then did nothing, and
     * Tilt and Shape sat clamped at 1.0 across almost their whole range, i.e.
     * felt dead. zoom_params.h documents this and says to use the 0..1 scaler;
     * this file was the last one still on the old helper. */
    float pInput   = zoom_param_norm01(params[TOTAPE9_INPUT_SLOT],   TOTAPE9_INPUT_DEFAULT_NORM);
    float pTilt    = zoom_param_norm01(params[TOTAPE9_TILT_SLOT],    TOTAPE9_TILT_DEFAULT_NORM);
    float pShape   = zoom_param_norm01(params[TOTAPE9_SHAPE_SLOT],   TOTAPE9_SHAPE_DEFAULT_NORM);
    float pFlutter = zoom_param_norm01(params[TOTAPE9_FLUTTER_SLOT], TOTAPE9_FLUTTER_DEFAULT_NORM);
    float pFlutSpd = zoom_param_norm01(params[TOTAPE9_FLUTSPD_SLOT], TOTAPE9_FLUTSPD_DEFAULT_NORM);
    float pBias    = zoom_param_norm01(params[TOTAPE9_BIAS_SLOT],    TOTAPE9_BIAS_DEFAULT_NORM);
    float pHeadBmp = zoom_param_norm01(params[TOTAPE9_HEADBMP_SLOT], TOTAPE9_HEADBMP_DEFAULT_NORM);
    float pOutput  = zoom_param_norm01(params[TOTAPE9_OUTPUT_SLOT], TOTAPE9_OUTPUT_DEFAULT_NORM);
    float pMix     = zoom_param_norm01(params[TOTAPE9_MIX_SLOT],  TOTAPE9_MIX_DEFAULT_NORM);

    float inputGain = pInput * 2.0f;
    inputGain *= inputGain;

    float dublyAmount = pTilt * 2.0f;
    float outlyAmount = (1.0f - pTilt) * -2.0f;
    if (outlyAmount < -1.0f) outlyAmount = -1.0f;

    float iirEncFreq = 1.0f - pShape;
    float iirDecFreq = pShape;

    float flutterPow2 = pFlutter * pFlutter;
    float flutterDepth = flutterPow2 * flutterPow2 * flutterPow2 * 50.0f;
    float flutSpdPow3 = pFlutSpd * pFlutSpd * pFlutSpd;
    float flutFrequency = 0.02f * flutSpdPow3;

    float bias = pBias * 2.0f - 1.0f;
    float underBias = bias * bias;
    underBias = underBias * underBias * 0.25f;
    float overBias = 1.0f - bias;
    overBias = overBias * overBias * overBias;
    if (bias > 0.0f) underBias = 0.0f;
    if (bias < 0.0f) overBias = 1.0f;

    float headBumpDrive = pHeadBmp * 0.1f;
    float headBumpMix = pHeadBmp * 0.5f;

    /* Stateless approximations of ToTape9's stateful blocks. These keep the
     * same source-derived knob tapers while avoiding large persistent memory. */
    float encodeAmt = dublyAmount * (0.35f + iirEncFreq * 0.65f);
    float decodeAmt = -outlyAmount * (0.35f + iirDecFreq * 0.65f);
    float tapeDrive = 1.0f + encodeAmt * 0.35f + headBumpDrive * 12.0f;
    /* HeadBmp alone now spans the whole lift range. HeadFrq used to scale this
     * same value by (200 - headHz)/175 -- it controlled no frequency, there is
     * no filter here, so the two knobs were adjusting one quantity between
     * them. Its slot went to Output, which the pack actually lacked. */
    float headLift = 1.0f + headBumpMix * 2.0f;
    /* Makeup gain after the tape stage, before the Mix crossfade: drive hard
     * with Input, then compensate. Losing this was a regression when Output
     * became Mix. */
    float outGain = pOutput * 2.0f;
    float flutterTrim = 1.0f - flutterDepth * flutFrequency * 0.1f;
    float biasCurve = bias * (0.12f + underBias * 0.18f + overBias * 0.018f);
    /* Tilt's own encode/decode balance. This is INTERNAL to the tape character
     * -- how much saturated path against clean path the machine itself runs --
     * and is not the user's Mix. */
    float tapeWet = 0.35f + encodeAmt * 0.25f + decodeAmt * 0.15f;
    if (tapeWet > 0.9f) tapeWet = 0.9f;
    float tapeDry = 1.0f - tapeWet;

    /* Mix is a real dry/wet crossfade against the untouched input, matching
     * every other effect in the pack. It replaces an output GAIN (pOutput*2),
     * which blended nothing and so gave no way to sit the tape against the dry
     * signal -- part of why levels across the pack never matched. */
    float wetLvl = pMix;
    float dryLvl = 1.0f - pMix;

    int i;
    for (i = 0; i < 16; i++) {
        float clean = fxBuf[i];              /* untouched, for the Mix crossfade */
        float x = clean * inputGain;
        float biased = x + biasCurve * x * x;
        float driven = biased * tapeDrive * flutterTrim * headLift;
        if (driven >  2.305929f) driven =  2.305929f;
        if (driven < -2.305929f) driven = -2.305929f;

        {
            float x2 = driven * driven;
            float p = driven * x2;
            float sat = driven;
            sat -= p * 0.16666667f;
            p *= x2;
            sat += p * 0.014492754f;
            p *= x2;
            sat -= p * 0.0003952447f;
            p *= x2;
            sat += p * 0.00000444473f;
            p *= x2;
            sat -= p * 0.000000100208f;
            float tape = x * tapeDry + sat * tapeWet;
            fxBuf[i] = dryLvl * clean + wetLvl * tape * outGain * TOTAPE9_WET_TRIM;
        }
    }
    return;
#else
#if !TOTAPE9_PERSISTENT_STATE
    float iirEncL = 0.0f, iirEncR = 0.0f;
    float compEncL = 1.0f, compEncR = 1.0f;
    float avgEncL = 0.0f, avgEncR = 0.0f;
    float iirDecL = 0.0f, iirDecR = 0.0f;
    float compDecL = 1.0f, compDecR = 1.0f;
    float avgDecL = 0.0f, avgDecR = 0.0f;
    float gslew[GSLEW_TOTAL];
    float hysteresisL = 0.0f, hysteresisR = 0.0f;
    float avg2L[2], avg2R[2];
    float post2L[2], post2R[2];
    int avgPos = 0;
    float lastDarkL = 0.0f, lastDarkR = 0.0f;
    float headBumpL = 0.0f, headBumpR = 0.0f;
    float hdbA[HDB_TOTAL], hdbB[HDB_TOTAL];
    float lastSampL = 0.0f, lastSampR = 0.0f;
    float intermedL = 0.0f, intermedR = 0.0f;
    float slewArrL[2], slewArrR[2];
    int wasPosClipL = 0, wasNegClipL = 0;
    int wasPosClipR = 0, wasNegClipR = 0;
    int z;
    for (z = 0; z < GSLEW_TOTAL; z++) gslew[z] = 0.0f;
    for (z = 0; z < HDB_TOTAL; z++) { hdbA[z] = 0.0f; hdbB[z] = 0.0f; }
    avg2L[0] = avg2L[1] = avg2R[0] = avg2R[1] = 0.0f;
    post2L[0] = post2L[1] = post2R[0] = post2R[1] = 0.0f;
    slewArrL[0] = slewArrL[1] = slewArrR[0] = slewArrR[1] = 0.0f;
#endif

    /* --- Decode context structure --- */
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);  /* L:[0..7] R:[8..15] */

    /* Magic pass-through (bookkeeping value the firmware expects) */
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    *magicDst = *magicSrc;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;

    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end = (uintptr_t)desc[1];
    unsigned int span = desc[2];
    uintptr_t stateBase = align4(base);
    uintptr_t requiredEnd = stateBase + sizeof(ToTape9State);
    uintptr_t bytes = end - base;

    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    if (bytes < sizeof(ToTape9State) || span < bytes) return;
    if (requiredEnd > end) return;

    ToTape9State *st = (ToTape9State *)stateBase;
    if (st->magic != TOTAPE9_MAGIC || st->version != TOTAPE9_VERSION) {
#ifdef TOTAPE9_SKIP_STATE_INIT
        /* Diagnostic build: bail out without running any state init. */
        return;
#else
        start_lazy_init(st);
        return;
#endif
    }
    if (!st->initialized) {
#ifdef TOTAPE9_HEADER_ONLY
        /* Diagnostic build: header write happened in start_lazy_init, but
         * never advance the chunked clear. Isolates the 16-byte header
         * write from the 512-byte chunk loop on hardware. */
        return;
#else
        clear_state_chunk(st);
        return;
#endif
    }
#ifdef TOTAPE9_INIT_ONLY
    /* Diagnostic build: lazy init has completed (initialized==1) but the
     * DSP body is skipped. Isolates "lazy init runs to completion" from
     * "DSP body executes". If T9InitOnly loads while T9NoHand freezes,
     * the freeze is in the DSP body, not the lazy clear. */
    return;
#endif

    float rawInput = params[TOTAPE9_INPUT_SLOT];
    float rawTilt = params[TOTAPE9_TILT_SLOT];
    float rawShape = params[TOTAPE9_SHAPE_SLOT];
    float rawFlutter = params[TOTAPE9_FLUTTER_SLOT];
    float rawFlutSpd = params[TOTAPE9_FLUTSPD_SLOT];
    float rawBias = params[TOTAPE9_BIAS_SLOT];
    float rawHeadBmp = params[TOTAPE9_HEADBMP_SLOT];
    /* Knob 8 is labelled OUTPUT and knob 9 MIX, and until now this block read them
     * as HeadFrq and Output -- everything from knob 8 on was shifted by one. So
     * "Output" moved a 25-200 Hz filter corner instead of the level, which is
     * exactly the "Output does nothing" it was reported as: it does something,
     * just never the thing written on it. There was no Mix at all.
     *
     * The shift survived because an earlier pass fixed it in the OTHER branch of
     * this file -- the one under `#if !TOTAPE9_FULL_DSP`, which does not compile:
     * TOTAPE9_FULL_DSP defaults to 1. The edit was real, it just never shipped.
     *
     * HeadFrq is retired rather than given a knob back. It was the least useful
     * control on the pedal and the pack has no room for it; the bump now sits at
     * a fixed 62 Hz, near the middle of its old travel and where a tape machine's
     * head bump actually lives. */
    float rawOutput = params[TOTAPE9_OUTPUT_SLOT];
    float rawMix    = params[TOTAPE9_MIX_SLOT];

    /* Bypass = clean dry passthrough, same off-gate as every other effect.
     * (An earlier build kept processing while "off" whenever the param block
     * looked unmaterialized, to dodge a reload mute -- but the host exposes a
     * BYPASSED effect's params as all-zero too, so that made a switched-OFF
     * Oxide keep running its up-to-2x output gain: louder when off. Reload
     * materialization is handled at the editor / knob-latch level instead.) */
    if (params[0] < 0.5f) return;
    float pInput = TOTAPE9_PARAM_NORM(rawInput, TOTAPE9_INPUT_DEFAULT_NORM);
    float pTilt = TOTAPE9_PARAM_NORM(rawTilt, TOTAPE9_TILT_DEFAULT_NORM);
    float pShape = TOTAPE9_PARAM_NORM(rawShape, TOTAPE9_SHAPE_DEFAULT_NORM);
    float pFlutter = TOTAPE9_PARAM_NORM(rawFlutter, TOTAPE9_FLUTTER_DEFAULT_NORM);
    float pFlutSpd = TOTAPE9_PARAM_NORM(rawFlutSpd, TOTAPE9_FLUTSPD_DEFAULT_NORM);
    float pBias = TOTAPE9_PARAM_NORM(rawBias, TOTAPE9_BIAS_DEFAULT_NORM);
    float pHeadBmp = TOTAPE9_PARAM_NORM(rawHeadBmp, TOTAPE9_HEADBMP_DEFAULT_NORM);
    const float pHeadFrq = 0.45f;          /* retired knob -> fixed ~62 Hz bump */
    float pOutput = TOTAPE9_PARAM_NORM(rawOutput, TOTAPE9_OUTPUT_DEFAULT_NORM);
    float pMixFull = TOTAPE9_PARAM_NORM(rawMix, TOTAPE9_MIX_DEFAULT_NORM);

    if (!TOTAPE9_PARAM_MISSING(rawInput)) st->cachedInput = pInput;
    else if (st->criticalParamCacheReady && st->cachedInput == st->cachedInput) pInput = zoom_clamp01(st->cachedInput);
    if (!TOTAPE9_PARAM_MISSING(rawBias)) st->cachedBias = pBias;
    else if (st->criticalParamCacheReady && st->cachedBias == st->cachedBias) pBias = zoom_clamp01(st->cachedBias);
    if (!TOTAPE9_PARAM_MISSING(rawOutput)) st->cachedOutput = pOutput;
    else if (st->criticalParamCacheReady && st->cachedOutput == st->cachedOutput) pOutput = zoom_clamp01(st->cachedOutput);

    /* Output level. 0..2x with unity at the knob's midpoint, applied to the
     * finished tape signal before Mix blends it against the dry. */
    float outputGain = pOutput * 2.0f;

    /* --- Derive algorithm parameters (matching ToTape9 formulas exactly)
     *     overallscale = 1.0 throughout                                  --- */

    float inputGain    = pInput * 2.0f; inputGain = inputGain * inputGain;
    /* Custom Oxide voicing: drive the tape harder without the full level jump. */
    if (inputGain > 1.0f) outputGain *= recip_approx_pos(oxide_drive_denominator(inputGain));

    float dublyAmount  = pTilt * 2.0f;
    float outlyAmount  = (1.0f - pTilt) * -2.0f;
    if (outlyAmount < -1.0f) outlyAmount = -1.0f;

    float iirEncFreq   = 1.0f - pShape;
    float iirDecFreq   = pShape;

    /* pow(D,6)*50, clamped to FLUTTER_BUF-2 */
    float fd = pFlutter * pFlutter;
    fd = fd * fd * fd;                           /* D^6 */
    float flutDepth    = fd * 50.0f;
    if (flutDepth > (float)(FLUTTER_BUF - 2)) flutDepth = (float)(FLUTTER_BUF - 2);

    float flutFreq     = 0.02f * pFlutSpd * pFlutSpd * pFlutSpd;

    float bias         = pBias * 2.0f - 1.0f;   /* –1 … +1 */
    float underBias    = bias * bias; underBias = underBias * underBias * 0.25f;
    float overBias     = (1.0f - bias); overBias = overBias * overBias * overBias;
    if (bias > 0.0f) underBias = 0.0f;
    if (bias < 0.0f) overBias  = 1.0f;

    /* Cascade gslew thresholds (every 3rd slot = threshold slot).
     * Reference assigns threshold9 (gslew[26]) the smallest value and
     * threshold1 (gslew[2]) the largest, so early stages are most permissive. */
    {
        float ob = overBias;
        gslew[26] = ob; ob *= PHI;   /* threshold9 – smallest */
        gslew[23] = ob; ob *= PHI;
        gslew[20] = ob; ob *= PHI;
        gslew[17] = ob; ob *= PHI;
        gslew[14] = ob; ob *= PHI;
        gslew[11] = ob; ob *= PHI;
        gslew[8]  = ob; ob *= PHI;
        gslew[5]  = ob; ob *= PHI;
        gslew[2]  = ob;              /* threshold1 – largest  */
    }

    float headBumpDrive = pHeadBmp * 0.1f;
    float headBumpMix   = pHeadBmp * 0.5f;

    /* HeadFrq: H^2 maps 0-1 to 25-200 Hz, normalised by 44100 */
    float hfA = (25.0f + pHeadFrq * pHeadFrq * 175.0f) * 0.000022675737f;
    float hfB = hfA * 0.9375f;
    float reso = 0.6180339887498948f;
    computeHDB(hdbA, hfA, reso);
    computeHDB(hdbB, hfB, reso);


#ifdef TOTAPE9_DSP_NO_LOOP
    /* Diagnostic build: run derived-params + computeHDB (which uses tanf
     * -> zoom_sinf), then return. Skips the 8-sample-pair processing loop
     * including dubly encode/decode, flutter, biquads, Taylor sat,
     * ClipOnly3. If T9DspNoLoop freezes, the freeze is in computeHDB or
     * derived params. If it loads, the for-loop body is the killer. */
    return;
#endif

    /* --- Process 8 stereo sample-pairs --- */
    float *fxL = fxBuf;       /* samples 0-7  */
    float *fxR = fxBuf + 8;   /* samples 8-15 */

    for (int i = 0; i < 8; i++)
    {
        float sL = fxL[i];
        float sR = fxR[i];
        /* Held for the Mix crossfade: this effect had no dry path at all, so it
         * could only ever be heard at full wet however its last knob was set. */
        const float cleanL = sL, cleanR = sR;

        /* == Input gain == */
        sL *= inputGain;
        sR *= inputGain;

        /* ================================================================
         * Dubly encode
         * ============================================================= */
        {
            /* Left */
            iirEncL = iirEncL * (1.0f - iirEncFreq) + sL * iirEncFreq;
            float hpL = (sL - iirEncL) * 2.848f + avgEncL;
            avgEncL   = (sL - iirEncL) * 1.152f;
            if (hpL >  1.0f) hpL =  1.0f;
            if (hpL < -1.0f) hpL = -1.0f;
            float dubL = hpL < 0.0f ? -hpL : hpL;
            if (dubL > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubL) * 0.41524199f;
                if (adj > 0.0f) dubL *= recip_approx_pos(adj);
                compEncL = compEncL * (1.0f - iirEncFreq) + dubL * iirEncFreq;
                sL += hpL * compEncL * dublyAmount;
            }
            /* Right */
            iirEncR = iirEncR * (1.0f - iirEncFreq) + sR * iirEncFreq;
            float hpR = (sR - iirEncR) * 2.848f + avgEncR;
            avgEncR   = (sR - iirEncR) * 1.152f;
            if (hpR >  1.0f) hpR =  1.0f;
            if (hpR < -1.0f) hpR = -1.0f;
            float dubR = hpR < 0.0f ? -hpR : hpR;
            if (dubR > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubR) * 0.41524199f;
                if (adj > 0.0f) dubR *= recip_approx_pos(adj);
                compEncR = compEncR * (1.0f - iirEncFreq) + dubR * iirEncFreq;
                sR += hpR * compEncR * dublyAmount;
            }
        }

        /* ================================================================
         * Flutter  (shared gcount write pointer, per original)
         * ============================================================= */
#if TOTAPE9_PERSISTENT_STATE
        if (flutDepth > 0.0f) {
            if (gcount < 0 || gcount >= FLUTTER_BUF) gcount = FLUTTER_BUF - 1;

            dL[gcount] = sL;
            dR[gcount] = sR;

            /* Left read */
            {
                float offset = flutDepth + flutDepth * sinf(sweepL);
                sweepL += nextmaxL * flutFreq;
                if (sweepL > 6.28318530718f) {
                    sweepL -= 6.28318530718f;
                    nextmaxL = 0.5f; /* simplified: drop random variation */
                }
                int cnt = gcount + (int)offset;
                if (cnt >= FLUTTER_BUF) cnt -= FLUTTER_BUF;
                int cnt1 = cnt + 1;
                if (cnt1 >= FLUTTER_BUF) cnt1 -= FLUTTER_BUF;
                float frac = offset - (float)(int)offset;
                sL = dL[cnt] * (1.0f - frac) + dL[cnt1] * frac;
            }
            /* Right read */
            {
                float offset = flutDepth + flutDepth * sinf(sweepR);
                sweepR += nextmaxR * flutFreq;
                if (sweepR > 6.28318530718f) {
                    sweepR -= 6.28318530718f;
                    nextmaxR = 0.5f;
                }
                int cnt = gcount + (int)offset;
                if (cnt >= FLUTTER_BUF) cnt -= FLUTTER_BUF;
                int cnt1 = cnt + 1;
                if (cnt1 >= FLUTTER_BUF) cnt1 -= FLUTTER_BUF;
                float frac = offset - (float)(int)offset;
                sR = dR[cnt] * (1.0f - frac) + dR[cnt1] * frac;
            }

            gcount--;
        }
#endif

        /* ================================================================
         * Bias  (9-stage slew limiter, gslew[x]=prevL, [x+1]=prevR, [x+2]=thresh)
         * ============================================================= */
        if (bias < -0.001f || bias > 0.001f) {
            for (int x = 0; x < GSLEW_TOTAL; x += 3) {
                float thr = gslew[x + 2];

                if (underBias > 0.0f) {
                    float stuck;
                    stuck = (sL - gslew[x]   * 1.02564103f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck *= recip_approx_pos(underBias);
                    if (stuck < 1.0f) sL = sL * stuck + (gslew[x]   * 1.02564103f) * (1.0f - stuck);

                    stuck = (sR - gslew[x+1] * 1.02564103f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck *= recip_approx_pos(underBias);
                    if (stuck < 1.0f) sR = sR * stuck + (gslew[x+1] * 1.02564103f) * (1.0f - stuck);
                }

                if ((sL - gslew[x])   >  thr) sL = gslew[x]   + thr;
                if ((gslew[x]   - sL) >  thr) sL = gslew[x]   - thr;
                gslew[x]   = sL * 0.975f;

                if ((sR - gslew[x+1]) >  thr) sR = gslew[x+1] + thr;
                if ((gslew[x+1] - sR) >  thr) sR = gslew[x+1] - thr;
                gslew[x+1] = sR * 0.975f;
            }
        }

        /* ================================================================
         * Tiny hysteresis
         * ============================================================= */
        {
            float abL = sL < 0.0f ? -sL : sL;
            float apL = (1.0f - abL) * (1.0f - abL) * 0.012f;
            hysteresisL += sL * abL;
            if (hysteresisL >  0.011449f) hysteresisL =  0.011449f;
            if (hysteresisL < -0.011449f) hysteresisL = -0.011449f;
            hysteresisL *= 0.999f;
            sL += hysteresisL * apL;

            float abR = sR < 0.0f ? -sR : sR;
            float apR = (1.0f - abR) * (1.0f - abR) * 0.012f;
            hysteresisR += sR * abR;
            if (hysteresisR >  0.011449f) hysteresisR =  0.011449f;
            if (hysteresisR < -0.011449f) hysteresisR = -0.011449f;
            hysteresisR *= 0.999f;
            sR += hysteresisR * apR;
        }

        /* ================================================================
         * TapeHack2 – pre-distortion smoothing  (avg2 only at 44100 Hz)
         * ============================================================= */
        {
            int pos = avgPos & 1;

            /* Left */
            float darkL = sL;
            avg2L[pos]  = darkL;
            darkL       = (avg2L[0] + avg2L[1]) * 0.5f;
            float slewL = (lastDarkL - sL) < 0.0f ? (sL - lastDarkL) : (lastDarkL - sL);
            slewL *= 0.12f;
            if (slewL > 1.0f) slewL = 1.0f;
            slewL   = 1.0f - (1.0f - slewL) * (1.0f - slewL);
            sL      = sL * (1.0f - slewL) + darkL * slewL;
            lastDarkL = darkL;

            /* Right */
            float darkR = sR;
            avg2R[pos]  = darkR;
            darkR       = (avg2R[0] + avg2R[1]) * 0.5f;
            float slewR = (lastDarkR - sR) < 0.0f ? (sR - lastDarkR) : (lastDarkR - sR);
            slewR *= 0.12f;
            if (slewR > 1.0f) slewR = 1.0f;
            slewR   = 1.0f - (1.0f - slewR) * (1.0f - slewR);
            sR      = sR * (1.0f - slewR) + darkR * slewR;
            lastDarkR = darkR;

            /* ============================================================
             * TapeHack – Taylor-series sin() approximation  (clamp ±2.306)
             * ========================================================== */
            /* Left */
            if (sL >  2.305929007734908f) sL =  2.305929007734908f;
            if (sL < -2.305929007734908f) sL = -2.305929007734908f;
            {
                float a2 = sL * sL;
                float em = sL * a2;          /* x^3  */  sL -= em * 0.16666667f;
                em *= a2;                    /* x^5  */  sL += em * 0.014492754f;
                em *= a2;                    /* x^7  */  sL -= em * 0.0003952447f;
                em *= a2;                    /* x^9  */  sL += em * 0.00000444473f;
                em *= a2;                    /* x^11 */  sL -= em * 0.000000100208f;
            }
            /* Right */
            if (sR >  2.305929007734908f) sR =  2.305929007734908f;
            if (sR < -2.305929007734908f) sR = -2.305929007734908f;
            {
                float a2 = sR * sR;
                float em = sR * a2;          sR -= em * 0.16666667f;
                em *= a2;                    sR += em * 0.014492754f;
                em *= a2;                    sR -= em * 0.0003952447f;
                em *= a2;                    sR += em * 0.00000444473f;
                em *= a2;                    sR -= em * 0.000000100208f;
            }

            /* TapeHack2 – post-distortion smoothing (avg2 only) */
            post2L[pos] = sL;
            float postDL = (post2L[0] + post2L[1]) * 0.5f;
            sL = sL * (1.0f - slewL) + postDL * slewL;

            post2R[pos] = sR;
            float postDR = (post2R[0] + post2R[1]) * 0.5f;
            sR = sR * (1.0f - slewR) + postDR * slewR;

            avgPos++;
        }

        /* ================================================================
         * Head bump  (nonlinear accumulator + two cascaded biquads)
         * ============================================================= */
        if (headBumpMix > 0.0f) {
            /* Left */
            headBumpL += sL * headBumpDrive;
            headBumpL -= headBumpL * headBumpL * headBumpL * 0.0618f;
            float biqL  = headBumpL * hdbA[HDB_A0] + hdbA[HDB_SL1];
            hdbA[HDB_SL1] = headBumpL * hdbA[HDB_A1] - biqL * hdbA[HDB_B1] + hdbA[HDB_SL2];
            hdbA[HDB_SL2] = headBumpL * hdbA[HDB_A2] - biqL * hdbA[HDB_B2];
            float hbsL  = biqL * hdbB[HDB_A0] + hdbB[HDB_SL1];
            hdbB[HDB_SL1] = biqL * hdbB[HDB_A1] - hbsL * hdbB[HDB_B1] + hdbB[HDB_SL2];
            hdbB[HDB_SL2] = biqL * hdbB[HDB_A2] - hbsL * hdbB[HDB_B2];
            sL += hbsL * headBumpMix;

            /* Right */
            headBumpR += sR * headBumpDrive;
            headBumpR -= headBumpR * headBumpR * headBumpR * 0.0618f;
            float biqR  = headBumpR * hdbA[HDB_A0] + hdbA[HDB_SR1];
            hdbA[HDB_SR1] = headBumpR * hdbA[HDB_A1] - biqR * hdbA[HDB_B1] + hdbA[HDB_SR2];
            hdbA[HDB_SR2] = headBumpR * hdbA[HDB_A2] - biqR * hdbA[HDB_B2];
            float hbsR  = biqR * hdbB[HDB_A0] + hdbB[HDB_SR1];
            hdbB[HDB_SR1] = biqR * hdbB[HDB_A1] - hbsR * hdbB[HDB_B1] + hdbB[HDB_SR2];
            hdbB[HDB_SR2] = biqR * hdbB[HDB_A2] - hbsR * hdbB[HDB_B2];
            sR += hbsR * headBumpMix;
        }

        /* ================================================================
         * Dubly decode
         * ============================================================= */
        {
            /* Left */
            iirDecL = iirDecL * (1.0f - iirDecFreq) + sL * iirDecFreq;
            float hpL = (sL - iirDecL) * 2.628f + avgDecL;
            avgDecL   = (sL - iirDecL) * 1.372f;
            if (hpL >  1.0f) hpL =  1.0f;
            if (hpL < -1.0f) hpL = -1.0f;
            float dubL = hpL < 0.0f ? -hpL : hpL;
            if (dubL > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubL) * 0.41524199f;
                if (adj > 0.0f) dubL *= recip_approx_pos(adj);
                compDecL = compDecL * (1.0f - iirDecFreq) + dubL * iirDecFreq;
                sL += hpL * compDecL * outlyAmount;
            }
            /* Right */
            iirDecR = iirDecR * (1.0f - iirDecFreq) + sR * iirDecFreq;
            float hpR = (sR - iirDecR) * 2.628f + avgDecR;
            avgDecR   = (sR - iirDecR) * 1.372f;
            if (hpR >  1.0f) hpR =  1.0f;
            if (hpR < -1.0f) hpR = -1.0f;
            float dubR = hpR < 0.0f ? -hpR : hpR;
            if (dubR > 0.0f) {
                float adj = logf(1.0f + 255.0f * dubR) * 0.41524199f;
                if (adj > 0.0f) dubR *= recip_approx_pos(adj);
                compDecR = compDecR * (1.0f - iirDecFreq) + dubR * iirDecFreq;
                sR += hpR * compDecR * outlyAmount;
            }
        }

        /* == Output gain == */
        sL *= outputGain;
        sR *= outputGain;

        /* ================================================================
         * ClipOnly3  (spacing = 1, so intermediate[] and slew[] are depth-1)
         * ============================================================= */
        /* Left */
        {
            float noise = 0.962f; /* simplified: omit PRNG, use fixed noise factor */
            if (wasPosClipL) {
                if (sL < lastSampL) lastSampL = 0.9085097f * noise + sL * (1.0f - noise);
                else                lastSampL = 0.94f;
            }
            wasPosClipL = 0;
            if (sL > 0.9085097f)  { wasPosClipL = 1; sL = 0.9085097f * noise + lastSampL * (1.0f - noise); }
            if (wasNegClipL) {
                if (sL > lastSampL) lastSampL = -0.9085097f * noise + sL * (1.0f - noise);
                else                lastSampL = -0.94f;
            }
            wasNegClipL = 0;
            if (sL < -0.9085097f) { wasNegClipL = 1; sL = -0.9085097f * noise + lastSampL * (1.0f - noise); }

            slewArrL[1] = slewArrL[0];
            slewArrL[0] = lastSampL - sL;
            if (slewArrL[0] < 0.0f) slewArrL[0] = -slewArrL[0];
            intermedL   = sL;
            sL          = lastSampL;
            lastSampL   = intermedL;

            float fs = slewArrL[0] > slewArrL[1] ? slewArrL[0] : slewArrL[1];
            float pc = 0.94f * recip_approx_pos(1.0f + fs * 1.3986013f);
            if (sL >  pc) sL =  pc;
            if (sL < -pc) sL = -pc;
        }
        /* Right */
        {
            float noise = 0.962f;
            if (wasPosClipR) {
                if (sR < lastSampR) lastSampR = 0.9085097f * noise + sR * (1.0f - noise);
                else                lastSampR = 0.94f;
            }
            wasPosClipR = 0;
            if (sR > 0.9085097f)  { wasPosClipR = 1; sR = 0.9085097f * noise + lastSampR * (1.0f - noise); }
            if (wasNegClipR) {
                if (sR > lastSampR) lastSampR = -0.9085097f * noise + sR * (1.0f - noise);
                else                lastSampR = -0.94f;
            }
            wasNegClipR = 0;
            if (sR < -0.9085097f) { wasNegClipR = 1; sR = -0.9085097f * noise + lastSampR * (1.0f - noise); }

            slewArrR[1] = slewArrR[0];
            slewArrR[0] = lastSampR - sR;
            if (slewArrR[0] < 0.0f) slewArrR[0] = -slewArrR[0];
            intermedR   = sR;
            sR          = lastSampR;
            lastSampR   = intermedR;

            float fs = slewArrR[0] > slewArrR[1] ? slewArrR[0] : slewArrR[1];
            float pc = 0.94f * recip_approx_pos(1.0f + fs * 1.3986013f);
            if (sR >  pc) sR =  pc;
            if (sR < -pc) sR = -pc;
        }

        /* ================================================================
         * Write back, scaled by on/off
         * ============================================================= */
        /* Output is a level on the finished signal, and Mix sits it against the
         * dry -- the order every other effect in the pack uses. */
        fxL[i] = cleanL * (1.0f - pMixFull) + sL * pMixFull;
        fxR[i] = cleanR * (1.0f - pMixFull) + sR * pMixFull;
    }
    /* (no return value; jump to B3 handled by compiler epilogue) */
#endif
}
