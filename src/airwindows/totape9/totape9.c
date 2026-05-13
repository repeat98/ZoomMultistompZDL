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
 *            ID9 = HeadFrq   A3[12]  0-1  → head-bump freq (H^2 → 25-200 Hz)
 *            ID10= Output    A3[13]  0-1  → output gain 0-2×
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

#include "../common/zoom_edit_handlers.h"
#include "../common/zoom_params.h"
#include "totape9_params.h"

#define TOTAPE9_PERSISTENT_STATE 1
#define TOTAPE9_FULL_DSP 1

ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Input_edit,   2, 20);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Tilt_edit,    3, 24);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Shape_edit,   4, 28);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Flutter_edit, 5, 32);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_FlutSpd_edit, 6, 36);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Bias_edit,    7, 40);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_HeadBmp_edit, 8, 44);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_HeadFrq_edit, 9, 48);
ZOOM_EDIT_HANDLER(Fx_FLT_ToTape9_Output_edit, 10, 52);

#if TOTAPE9_FULL_DSP
/* =========================================================================
 * Inline math functions
 *
 * The Zoom ZDL runtime does not provide sinf/logf/tanf.  No stock Zoom
 * effect uses them, so they are not in the firmware's RTS.  We provide
 * lightweight inline versions here so the compiler folds them into the
 * .audio section and no external symbol reference is generated.
 *
 * __c6xabi_divf (float divide) IS available – we extract it from stock
 * ZDL binaries where it's statically linked.  So the `/` operator is fine.
 *
 * Accuracy targets:  ~20-bit mantissa (sufficient for audio, IEEE single
 * has 24-bit mantissa).  These are NOT fully IEEE-754 compliant – no
 * special-case handling for NaN/Inf/denormals.
 * ====================================================================== */

/* --- sinf: Bhaskara I approximation, max error ~0.0016 --------------- */
static float zoom_sinf(float x)
{
    /* Reduce x to [0, 2*pi) */
    const float TWO_PI  = 6.2831853f;
    const float PI      = 3.1415927f;
    const float INV_2PI = 0.15915494f;

    /* Range reduction: x = x mod 2*pi, result in [0, 2*pi) */
    x = x - TWO_PI * (float)(int)(x * INV_2PI);
    if (x < 0.0f) x += TWO_PI;

    /* Use symmetry to map to [0, pi] */
    float sign = 1.0f;
    if (x > PI) { x -= PI; sign = -1.0f; }

    /* Bhaskara I: sin(x) ≈ 16x(pi-x) / (5*pi^2 - 4x(pi-x))
       Max error ~0.0016 over [0, pi] */
    float pmx = PI - x;
    float xpmx = x * pmx;
    return sign * (16.0f * xpmx) / (49.348f - 4.0f * xpmx);
}

/* --- logf: bit-hack + polynomial correction -------------------------- */
static float zoom_logf(float x)
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

/* --- tanf: sin/cos via paired Bhaskara ------------------------------- */
static float zoom_tanf(float x)
{
    /* tan(x) = sin(x) / cos(x) */
    const float HALF_PI = 1.5707963f;
    return zoom_sinf(x) / zoom_sinf(x + HALF_PI);
}

/* Redirect standard names */
#define sinf(x) zoom_sinf(x)
#define logf(x) zoom_logf(x)
#define tanf(x) zoom_tanf(x)
#endif

#pragma CODE_SECTION(Fx_FLT_ToTape9, ".audio")

/*
 * On the TI C674x (32-bit target) sizeof(unsigned int) == sizeof(void*) == 4,
 * so the pointer casts below are correct.  On a 64-bit host (used only for
 * syntax-checking) the compiler will warn; those warnings are expected and safe
 * to ignore.
 */
#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* -------------------------------------------------------------------------
 * Constants
 * ---------------------------------------------------------------------- */

#define FLUTTER_BUF  1002
#define PHI          1.6180339887498948f
#define KNOB_NORM    (1.0f / 0.14f)

#define TOTAPE9_MAGIC 0x54395039u
#define TOTAPE9_VERSION 1u

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

typedef struct ToTape9State {
    uint32_t magic;
    uint32_t version;

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

static inline float totape9_param_norm(float raw, float fallback_norm)
{
    if (raw <= 0.0001f) return zoom_clamp01(fallback_norm);
    if (raw <= 1.0f) return zoom_clamp01(raw);
    return zoom_clamp01(raw * 0.01f);
}

static void reset_totape9_state(ToTape9State *st)
{
    int i;
    unsigned char *p = (unsigned char *)st;
    for (i = 0; i < (int)sizeof(ToTape9State); i++) {
        p[i] = 0u;
    }

    st->magic = TOTAPE9_MAGIC;
    st->version = TOTAPE9_VERSION;
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
static void computeHDB(float *hdb, float normalizedFreq, float reso)
{
    hdb[HDB_FREQ] = normalizedFreq;
    hdb[HDB_RESO] = reso;
    hdb[HDB_A1]   = 0.0f;
    float K    = tanf(3.14159265358979323f * normalizedFreq);
    float norm = 1.0f / (1.0f + K / reso + K * K);
    hdb[HDB_A0] =  K / reso * norm;
    hdb[HDB_A2] = -hdb[HDB_A0];
    hdb[HDB_B1] =  2.0f * (K * K - 1.0f) * norm;
    hdb[HDB_B2] =  (1.0f - K / reso + K * K) * norm;
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

void Fx_FLT_ToTape9(unsigned int *ctx)
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
     * freezes hardware while preserving the source parameter control laws. */
    float pInput   = zoom_param_norm(params[TOTAPE9_INPUT_SLOT],   TOTAPE9_INPUT_DEFAULT_NORM);
    float pTilt    = zoom_param_norm(params[TOTAPE9_TILT_SLOT],    TOTAPE9_TILT_DEFAULT_NORM);
    float pShape   = zoom_param_norm(params[TOTAPE9_SHAPE_SLOT],   TOTAPE9_SHAPE_DEFAULT_NORM);
    float pFlutter = zoom_param_norm(params[TOTAPE9_FLUTTER_SLOT], TOTAPE9_FLUTTER_DEFAULT_NORM);
    float pFlutSpd = zoom_param_norm(params[TOTAPE9_FLUTSPD_SLOT], TOTAPE9_FLUTSPD_DEFAULT_NORM);
    float pBias    = zoom_param_norm(params[TOTAPE9_BIAS_SLOT],    TOTAPE9_BIAS_DEFAULT_NORM);
    float pHeadBmp = zoom_param_norm(params[TOTAPE9_HEADBMP_SLOT], TOTAPE9_HEADBMP_DEFAULT_NORM);
    float pHeadFrq = zoom_param_norm(params[TOTAPE9_HEADFRQ_SLOT], TOTAPE9_HEADFRQ_DEFAULT_NORM);
    float pOutput  = zoom_param_norm(params[TOTAPE9_OUTPUT_SLOT],  TOTAPE9_OUTPUT_DEFAULT_NORM);

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
    float headHz = pHeadFrq * pHeadFrq * 175.0f + 25.0f;
    float outputGain = pOutput * 2.0f;

    /* Stateless approximations of ToTape9's stateful blocks. These keep the
     * same source-derived knob tapers while avoiding large persistent memory. */
    float encodeAmt = dublyAmount * (0.35f + iirEncFreq * 0.65f);
    float decodeAmt = -outlyAmount * (0.35f + iirDecFreq * 0.65f);
    float tapeDrive = 1.0f + encodeAmt * 0.35f + headBumpDrive * 12.0f;
    float headLift = 1.0f + headBumpMix * (1.0f + (200.0f - headHz) * (1.0f / 175.0f));
    float flutterTrim = 1.0f - flutterDepth * flutFrequency * 0.1f;
    float biasCurve = bias * (0.12f + underBias * 0.18f + overBias * 0.018f);
    float wet = 0.35f + encodeAmt * 0.25f + decodeAmt * 0.15f;
    if (wet > 0.9f) wet = 0.9f;
    float dry = 1.0f - wet;

    int i;
    for (i = 0; i < 16; i++) {
        float x = fxBuf[i] * inputGain;
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
            fxBuf[i] = (x * dry + sat * wet) * outputGain;
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

    if (params[0] < 0.5f) return;

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
        reset_totape9_state(st);
    }

    float pInput   = totape9_param_norm(params[TOTAPE9_INPUT_SLOT],   TOTAPE9_INPUT_DEFAULT_NORM);
    float pTilt    = totape9_param_norm(params[TOTAPE9_TILT_SLOT],    TOTAPE9_TILT_DEFAULT_NORM);
    float pShape   = totape9_param_norm(params[TOTAPE9_SHAPE_SLOT],   TOTAPE9_SHAPE_DEFAULT_NORM);
    float pFlutter = totape9_param_norm(params[TOTAPE9_FLUTTER_SLOT], TOTAPE9_FLUTTER_DEFAULT_NORM);
    float pFlutSpd = totape9_param_norm(params[TOTAPE9_FLUTSPD_SLOT], TOTAPE9_FLUTSPD_DEFAULT_NORM);
    float pBias    = totape9_param_norm(params[TOTAPE9_BIAS_SLOT],    TOTAPE9_BIAS_DEFAULT_NORM);
    float pHeadBmp = totape9_param_norm(params[TOTAPE9_HEADBMP_SLOT], TOTAPE9_HEADBMP_DEFAULT_NORM);
    float pHeadFrq = totape9_param_norm(params[TOTAPE9_HEADFRQ_SLOT], TOTAPE9_HEADFRQ_DEFAULT_NORM);
    float pOutput  = totape9_param_norm(params[TOTAPE9_OUTPUT_SLOT],  TOTAPE9_OUTPUT_DEFAULT_NORM);

    /* --- Derive algorithm parameters (matching ToTape9 formulas exactly)
     *     overallscale = 1.0 throughout                                  --- */

    float inputGain    = pInput * 2.0f; inputGain = inputGain * inputGain;

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
    float hfA = (25.0f + pHeadFrq * pHeadFrq * 175.0f) / 44100.0f;
    float hfB = hfA * 0.9375f;
    float reso = 0.6180339887498948f;
    computeHDB(hdbA, hfA, reso);
    computeHDB(hdbB, hfB, reso);

    float outputGain = pOutput * 2.0f;

    /* --- Process 8 stereo sample-pairs --- */
    float *fxL = fxBuf;       /* samples 0-7  */
    float *fxR = fxBuf + 8;   /* samples 8-15 */

    for (int i = 0; i < 8; i++)
    {
        float sL = fxL[i];
        float sR = fxR[i];

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
                float adj = logf(1.0f + 255.0f * dubL) / 2.40823996531f;
                if (adj > 0.0f) dubL /= adj;
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
                float adj = logf(1.0f + 255.0f * dubR) / 2.40823996531f;
                if (adj > 0.0f) dubR /= adj;
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
                    stuck = (sL - gslew[x]   / 0.975f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck /= underBias;
                    if (stuck < 1.0f) sL = sL * stuck + (gslew[x]   / 0.975f) * (1.0f - stuck);

                    stuck = (sR - gslew[x+1] / 0.975f);
                    if (stuck < 0.0f) stuck = -stuck;
                    stuck /= underBias;
                    if (stuck < 1.0f) sR = sR * stuck + (gslew[x+1] / 0.975f) * (1.0f - stuck);
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
                float em = sL * a2;          /* x^3  */  sL -= em / 6.0f;
                em *= a2;                    /* x^5  */  sL += em / 69.0f;
                em *= a2;                    /* x^7  */  sL -= em / 2530.08f;
                em *= a2;                    /* x^9  */  sL += em / 224985.6f;
                em *= a2;                    /* x^11 */  sL -= em / 9979200.0f;
            }
            /* Right */
            if (sR >  2.305929007734908f) sR =  2.305929007734908f;
            if (sR < -2.305929007734908f) sR = -2.305929007734908f;
            {
                float a2 = sR * sR;
                float em = sR * a2;          sR -= em / 6.0f;
                em *= a2;                    sR += em / 69.0f;
                em *= a2;                    sR -= em / 2530.08f;
                em *= a2;                    sR += em / 224985.6f;
                em *= a2;                    sR -= em / 9979200.0f;
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
                float adj = logf(1.0f + 255.0f * dubL) / 2.40823996531f;
                if (adj > 0.0f) dubL /= adj;
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
                float adj = logf(1.0f + 255.0f * dubR) / 2.40823996531f;
                if (adj > 0.0f) dubR /= adj;
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
            float pc = 0.94f / (1.0f + fs * 1.3986013f);
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
            float pc = 0.94f / (1.0f + fs * 1.3986013f);
            if (sR >  pc) sR =  pc;
            if (sR < -pc) sR = -pc;
        }

        /* ================================================================
         * Write back, scaled by on/off
         * ============================================================= */
        fxL[i] = sL;
        fxR[i] = sR;
    }
    /* (no return value; jump to B3 handled by compiler epilogue) */
#endif
}
