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
 * handler convention). Multiply by 1/0.14 ~ 7.14 to land 0..1, then by
 * 10 / 0.9239 to match the original's gains. */
#define DRIVE_SCALE   (10.0f / 0.14f)        /* raw 0..0.14 -> 0..10x */
#define OUTPUT_SCALE  (0.9239f / 0.14f)      /* raw 0..0.14 -> 0..0.9239x */
#define CLIP_LIMIT    2.305929f


static inline float clipf_(float x, float lim)
{
    if (x >  lim) return  lim;
    if (x < -lim) return -lim;
    return x;
}


/* TapeHack's "degenerate Taylor sin" — odd terms 1,3,5,7,9,11.
 * Valid for |x| up to ~2.31 (where sin starts curving back). */
static inline float taylor_sin(float x)
{
    float xx     = x * x;          /* x^2 */
    float power  = x * xx;         /* x^3 */
    float result = x;
    result -= power / 6.0f;
    power  *= xx;                  /* x^5  */
    result += power / 69.0f;
    power  *= xx;                  /* x^7  */
    result -= power / 2530.08f;
    power  *= xx;                  /* x^9  */
    result += power / 224985.6f;
    power  *= xx;                  /* x^11 */
    result -= power / 9979200.0f;
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

    float onoff      = params[0];
    float inputGain  = params[5] * DRIVE_SCALE  * onoff;
    float outputGain = params[6] * OUTPUT_SCALE * onoff;

    /* Block layout: 8 L samples then 8 R samples. */
    int i;
    for (i = 0; i < 16; i++) {
        float s = clipf_(fxBuf[i] * inputGain, CLIP_LIMIT);
        fxBuf[i] = taylor_sin(s) * outputGain;
    }
}
