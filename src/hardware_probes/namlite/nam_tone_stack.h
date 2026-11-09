/* Bass / Middle / Treble after the NAM network -- see
 * tools/nam_prototype/tone_stack.py for the design (NAM-plugin voicing) and
 * the generated coefficient table.
 *
 * Transposed direct form II, two state floats per band. No branches inside:
 * the row is chosen once per callback, and each sample is five multiplies and
 * four adds per band. At knob 50 the coefficients make each biquad an exact
 * identity, so a flat EQ changes nothing, bit for bit. */
#ifndef NAM_TONE_STACK_H
#define NAM_TONE_STACK_H
#include "nam_tone_table.h"

/* norm is the knob as 0..1; returns that knob's {b0,b1,b2,a1,a2}. Signed int
 * conversion on purpose: float->unsigned pulls in __c6xabi_fixfu (a freeze). */
#pragma FUNC_ALWAYS_INLINE(nam_tone_row)
static inline const float *nam_tone_row(unsigned band, float norm)
{
    int k = (int)(norm * 100.0f + 0.5f);
    if (k < 0) k = 0;
    if (k > 100) k = 100;
#if NAM_TONE_STEP == 2
    return nam_tone[band][(k + 1) >> 1];    /* half table: rows are knobs 0,2,..,100 */
#else
    return nam_tone[band][k];
#endif
}

#pragma FUNC_ALWAYS_INLINE(nam_biquad)
static inline float nam_biquad(const float *c, float *z, float u)
{
    float o = c[0] * u + z[0];
    z[0] = c[1] * u - c[3] * o + z[1];
    z[1] = c[2] * u - c[4] * o;
    return o;
}
#endif
