/*
 * bitcrush.c -- BitCrush effect for Zoom MS-70CDR
 *
 * Two-knob bit crusher. Stateless, no runtime-helper calls (no divf,
 * no push_rts/pop_rts, no .const placeholders). The whole thing
 * compiles to integer shifts, float bit-manipulation, and a couple
 * MPYSPs — guaranteed to exercise the audio path with an audibly
 * obvious effect, so we can isolate any DSP-vs-firmware question.
 *
 * Knobs:
 *   Crush  (params[5])  AND-mask the float mantissa, 0..16 bits cleared.
 *                       0 = clean, max = brutal quantization fuzz.
 *   Rate   (params[6])  Sample-and-hold decimation, hold every 1/2/4/8
 *                       samples (power-of-2 step). Max = blocky aliasing
 *                       roughly equivalent to a 5.5 kHz sample rate.
 *
 * The "state" between blocks resets — at maximum decim the held value
 * starts fresh from the new block's first sample. The block-rate
 * discontinuity is part of the BitCrush sound; embrace it.
 */

#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_BitCrush, ".audio")

#define ZDL_PTR(type, word)  ((type)(uintptr_t)(word))

/* params[5] / params[6] arrive at ~0.14 at full knob (LineSel handler
 * convention). Pre-fold the scaling: multiplying by these constants
 * lands int values in the desired [0,16] / [0,3] range at the rails. */
#define CRUSH_SCALE  (16.0f / 0.14f)   /* raw 0..0.14 -> shift 0..16 */
#define RATE_SCALE   ( 3.0f / 0.14f)   /* raw 0..0.14 -> pow   0..3  */


void Fx_FLT_BitCrush(unsigned int *ctx)
{
    float        *params   = ZDL_PTR(float        *, ctx[1]);
    float        *fxBuf    = ZDL_PTR(float        *, ctx[5]);

    /* Magic shuttle - preserve. */
    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;  /* bypassed - magic shuttle handles passthrough */

    /* Crush amount: how many low mantissa bits to AND-clear. */
    int crush_shift = (int)(params[5] * CRUSH_SCALE);
    if (crush_shift < 0)  crush_shift = 0;
    if (crush_shift > 16) crush_shift = 16;
    uint32_t mask = ~((1u << crush_shift) - 1u);

    /* Decim power: 0..3 -> hold every 1/2/4/8 samples. */
    int rate_pow = (int)(params[6] * RATE_SCALE);
    if (rate_pow < 0) rate_pow = 0;
    if (rate_pow > 3) rate_pow = 3;
    int decim_mask = (1 << rate_pow) - 1;

    /* L channel: samples 0..7. The (i & decim_mask) == 0 test always
     * passes on i=0, so the initial held_L value is overwritten before
     * first read; no init needed. */
    union { float f; uint32_t u; } held_L, v;
    held_L.f = 0.0f;
    int i;
    for (i = 0; i < 8; i++) {
        if ((i & decim_mask) == 0) {
            v.f   = fxBuf[i];
            v.u  &= mask;
            held_L.f = v.f;
        }
        fxBuf[i] = held_L.f;
    }

    /* R channel: samples 8..15. */
    union { float f; uint32_t u; } held_R;
    held_R.f = 0.0f;
    for (i = 0; i < 8; i++) {
        if ((i & decim_mask) == 0) {
            v.f   = fxBuf[i + 8];
            v.u  &= mask;
            held_R.f = v.f;
        }
        fxBuf[i + 8] = held_R.f;
    }
}
