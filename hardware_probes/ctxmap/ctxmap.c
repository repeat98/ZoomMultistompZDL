/*
 * ctxmap.c
 *
 * Zoom Multistomp hardware ABI probe.
 *
 * Goal
 * ----
 * Airwindows exact ports need persistent state. Stock Zoom effects appear to
 * receive one or more host-owned state/scratch descriptors through ctx[].
 * This probe maps ctx words safely: it reads ctx[Slot] as a 32-bit value and
 * emits a square-wave tone when Bit is set. It never dereferences the selected
 * ctx word, so slots that happen to be null, small integers, pointers, or
 * flags are equally safe to inspect.
 *
 * v2 note: the first build crashed when the Bit control was edited on
 * hardware. That build used object-defined inline-asm edit handlers. This
 * version deliberately has only two controls, so the linker can use the
 * stock-proven LineSel edit handlers for both controls.
 *
 * v3 note: the stock-handler build did not crash, but also produced no
 * audible output. This version removes dependence on params[0], restores
 * the 0..31 bit range, emits a quiet baseline tone for every setting, and
 * writes the diagnostic tone to both ctx[5] and ctx[6].
 *
 * v4 note: the parameter-audibility variant crashed the pedal on startup.
 * This file is rolled back to the last hardware-surviving v3 behavior until
 * we split risky probes into separate effect IDs.
 *
 * Known-safe ABI fields reused from the existing custom probes:
 *   ctx[1]  -> params table (float*)
 *   ctx[5]  -> fx buffer (float*)
 *   ctx[6]  -> output accumulator (float*)
 *   ctx[11] -> magic destination indirection
 *   ctx[12] -> magic source
 *
 * Use
 * ---
 * Load on hardware, send silence or guitar through it, then sweep Slot 0..15
 * and Bit 0..31. A louder tone means that bit is 1; a quiet tone means it is
 * 0. Record the output if possible.
 */

#include <stdint.h>

#include "../../src/airwindows/common/zoom_params.h"
#include "ctxmap_params.h"

#pragma CODE_SECTION(Fx_FLT_CtxMap, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#pragma DATA_SECTION(gPhase, ".fardata")
static unsigned int gPhase = 0;

static int ctxmap_scaled_index(float raw, int max_value)
{
    float n = zoom_clamp01(raw * ZOOM_PARAM_RAW_TO_NORM);
    return (int)(n * ((float)max_value + 0.999f));
}

void Fx_FLT_CtxMap(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    int slot = ctxmap_scaled_index(params[CTXMAP_SLOT_SLOT], CTXMAP_SLOT_UI_MAX);
    int bit = ctxmap_scaled_index(params[CTXMAP_BIT_SLOT], CTXMAP_BIT_UI_MAX);

    unsigned int word = ctx[(unsigned int)slot & 15u];
    unsigned int bit_on = (word >> ((unsigned int)bit & 31u)) & 1u;
    float amp = bit_on ? 0.055f : 0.012f;

    int i;
    for (i = 0; i < 16; i++) {
        float tone;

        gPhase += 1u;
        tone = (gPhase & 32u) ? amp : -amp;
        fxBuf[i] += tone;
        outBuf[i] += tone;
    }
}
