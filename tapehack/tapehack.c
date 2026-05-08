/*
 * tapehack.c -- TapeHack port for Zoom MS-70CDR
 *
 * Source: airwindows-ref/plugins/WinVST/TapeHack/TapeHackProc.cpp
 * Original (c) Chris Johnson (airwindows), MIT licence.
 *
 * Algorithm: drive the signal up to ~10x, hard-clip to +/-2.305929, then
 * apply an 11th-order odd Taylor expansion of sin() to introduce harmonic
 * saturation. Output trim re-attenuates. Stateless — no per-instance
 * memory needed, so this sidesteps the unsolved-on-MS-70CDR static far
 * BSS problem.
 *
 * Knobs:
 *   Drive  (params[5])  inputGain 0..10x
 *   Output (params[6])  outputGain 0..0.9239 (matches stock airwindows)
 *
 * Original TapeHack has a third "Wet" knob; we hardcode wet=1 because
 * the LineSel handler blob we splice in only provides edit handlers for
 * knobs 1+2. Adding wet means extracting a knob3 edit handler from a
 * stock 3-knob effect (AIR is the obvious candidate).
 *
 * Skipped from the desktop original:
 *   - 32-bit FP dither (would need frexpf/pow)
 *   - 1.18e-23 denormal-flush guard (audio levels here won't get there)
 */

#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_TapeHack, ".audio")

#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))


/* params[5] / params[6] arrive scaled by ~0.14 at full knob (LineSel
 * handler convention). MS-70CDR's effect-loop signal is much hotter
 * than -15dBFS guitar, so even unity through the Taylor polynomial
 * saturates audibly. We use Drive as a wet/dry blend AND preamp control
 * simultaneously: at drive=0, output is bit-perfect dry; as drive
 * ramps, preamp grows 1x..3x and wet mix grows 0..100%. Output is a
 * straight 0..0.9x trim with a hair of headroom for the polynomial's
 * ~1.08 peak. */
#define DRIVE_NORM    (1.0f / 0.14f)         /* raw 0..0.14 -> intensity 0..1 */
#define OUTPUT_SCALE  (0.9f / 0.14f)         /* raw 0..0.14 -> 0..0.9x */
#define MAX_BOOST     2.0f                   /* preamp at full drive = 1 + MAX_BOOST */
#define CLIP_LIMIT    2.305929f


static inline float clipf_(float x, float lim)
{
    if (x >  lim) return  lim;
    if (x < -lim) return -lim;
    return x;
}


/* TapeHack's "degenerate Taylor sin" — odd terms 1,3,5,7,9,11.
 * Valid for |x| up to ~2.31 (where sin starts curving back).
 *
 * Each divisor is replaced by its precomputed reciprocal so the compiler
 * lowers each step to a single MPYSP. Avoiding `x / const` here is
 * critical: cl6x emits a __c6xabi_divf call for runtime float divide,
 * and our spliced divf RTS hasn't been verified on hardware (640-byte
 * blob; canonical divf is ~50 instructions, so what we have is suspect).
 * Multiplying by reciprocal sidesteps the issue completely. */
#define INV_6        (1.0f / 6.0f)
#define INV_69       (1.0f / 69.0f)
#define INV_2530_08  (1.0f / 2530.08f)
#define INV_224985_6 (1.0f / 224985.6f)
#define INV_9979200  (1.0f / 9979200.0f)

static inline float taylor_sin(float x)
{
    float xx     = x * x;          /* x^2 */
    float power  = x * xx;         /* x^3 */
    float result = x;
    result -= power * INV_6;
    power  *= xx;                  /* x^5  */
    result += power * INV_69;
    power  *= xx;                  /* x^7  */
    result -= power * INV_2530_08;
    power  *= xx;                  /* x^9  */
    result += power * INV_224985_6;
    power  *= xx;                  /* x^11 */
    result -= power * INV_9979200;
    return result;
}


void Fx_FLT_TapeHack(unsigned int *ctx)
{
    float        *params   = ZDL_PTR(float        *, ctx[1]);
    float        *fxBuf    = ZDL_PTR(float        *, ctx[5]);

    /* Magic shuttle - preserve. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* Bypassed: magic shuttle already passes the dry signal through fxBuf,
     * so we leave it alone. Without this early return, the DSP zeros the
     * audio at onoff=0 and bypass becomes a hard mute. */
    if (params[0] < 0.5f) return;

    float intensity  = params[5] * DRIVE_NORM;            /* 0..1 */
    float outputGain = params[6] * OUTPUT_SCALE;          /* 0..0.9 */
    float boost      = 1.0f + intensity * MAX_BOOST;      /* 1..3x */
    float dry_mix    = 1.0f - intensity;
    float wet_mix    = intensity;

    /* Block layout: 8 L samples then 8 R samples. */
    int i;
    for (i = 0; i < 16; i++) {
        float dry = fxBuf[i];
        float s   = clipf_(dry * boost, CLIP_LIMIT);
        float wet = taylor_sin(s);
        fxBuf[i]  = (dry * dry_mix + wet * wet_mix) * outputGain;
    }
}
