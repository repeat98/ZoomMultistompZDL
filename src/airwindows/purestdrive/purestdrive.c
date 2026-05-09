/*
 * purestdrive.c -- PurestDrive port for Zoom MS-70CDR
 *
 * Source: airwindows-ref/plugins/WinVST/PurestDrive/PurestDriveProc.cpp
 * Original (c) Chris Johnson (airwindows), MIT licence.
 *
 * Algorithm summary:
 *   For each sample:
 *     dry  = input
 *     sat  = sin(dry)
 *     blend = |prevSat + sat| / 2 * intensity        // adaptive amount
 *     out  = dry * (1 - blend) + sat * blend
 *     prev = sin(dry)                                 // store for next call
 *
 *   The adaptive `blend` term lets through highs/transients more openly
 *   than a static dry/wet, giving the "Purest" character vs ordinary sin
 *   saturation.
 *
 *   Original PurestDriveProc dithers the output (32-bit FP dither). We
 *   skip it — speakers + guitar audio won't reveal the difference and
 *   it would pull in frexpf/pow.
 *
 * Differences from the desktop original:
 *   - Float (not double) — C674x has hardware float; we do not need 64.
 *   - No dither (see above).
 *   - No denormal-flush kludge (audio levels here won't hit 1e-23).
 *   - sinf() replaced with an inline Bhaskara-I approximation; firmware
 *     RTS does not expose sinf.
 */

#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_PurestDr, ".audio")

#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* DIAGNOSTIC build: previousSampleL/R were originally `static` (in .far
 * BSS), but the .fardata segment the firmware maps is exactly 24 bytes
 * (KNOB_INFO only) — every stock ZDL has the same. Writing to
 * FARDATA_VA + 24 traps the DSP and freezes the pedal on load. Until we
 * figure out the proper per-effect state mechanism (probably a ctx
 * pointer slot), keep them as stack locals: state is lost across blocks
 * but at 48kHz/8-sample blocks the algorithm should still drive. */


/* sin(x) approximation, ~3-decimal accuracy, ample for audio.
 * Bhaskara I: sin(x) ~= 16x(pi-x) / (5*pi^2 - 4x(pi-x))   for x in [0,pi]
 * Range reduction: x mod 2*pi, sign flip for the second half. */
static float zoom_sinf(float x)
{
    const float TWO_PI  = 6.2831853f;
    const float PI      = 3.1415927f;
    const float INV_2PI = 0.15915494f;

    x = x - TWO_PI * (float)(int)(x * INV_2PI);
    if (x < 0.0f) x += TWO_PI;

    float sign = 1.0f;
    if (x > PI) { x -= PI; sign = -1.0f; }

    float pmx  = PI - x;
    float xpmx = x * pmx;
    return sign * (16.0f * xpmx) / (49.348f - 4.0f * xpmx);
}


static inline float fabsf_(float x) { return x < 0.0f ? -x : x; }


void Fx_FLT_PurestDr(unsigned int *ctx)
{
    float        *params   = ZDL_PTR(float        *, ctx[1]);
    float        *fxBuf    = ZDL_PTR(float        *, ctx[5]);

    /* Magic shuttle - preserve. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* Drive knob lives at params[5] (LineSel handler convention).
     * GAIN testing showed the raw value lands ~ 0.14 at full knob, so
     * we scale 8x to spread it across 0..1 of "intensity". */
    float onoff     = params[0];
    float intensity = params[5] * 8.0f * onoff;
    if (intensity < 0.0f) intensity = 0.0f;
    if (intensity > 1.0f) intensity = 1.0f;

    /* Block layout: 8 L samples then 8 R samples.  Per-block state
     * (previousSample reset to 0 each block, see top-of-file note). */
    float previousSampleL = 0.0f;
    float previousSampleR = 0.0f;
    int i;
    for (i = 0; i < 8; i++) {
        float dry   = fxBuf[i];
        float sat   = zoom_sinf(dry);
        float blend = fabsf_(previousSampleL + sat) * 0.5f * intensity;
        if (blend > 1.0f) blend = 1.0f;
        fxBuf[i] = dry * (1.0f - blend) + sat * blend;
        previousSampleL = zoom_sinf(dry);
    }
    for (i = 8; i < 16; i++) {
        float dry   = fxBuf[i];
        float sat   = zoom_sinf(dry);
        float blend = fabsf_(previousSampleR + sat) * 0.5f * intensity;
        if (blend > 1.0f) blend = 1.0f;
        fxBuf[i] = dry * (1.0f - blend) + sat * blend;
        previousSampleR = zoom_sinf(dry);
    }
}
