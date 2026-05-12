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
 * and Bit 0..31. A tone means that bit is 1; silence means it is 0. Record the
 * output if possible, because each reconstructed ctx word is evidence for the
 * exact state ABI we need before porting state-heavy Airwindows algorithms.
 */

#include <stdint.h>

#include "../common/zoom_edit_handlers.h"
#include "../common/zoom_params.h"
#include "ctxmap_params.h"

ZOOM_EDIT_HANDLER(Fx_FLT_CtxMap_Slot_edit,  2, 20);
ZOOM_EDIT_HANDLER(Fx_FLT_CtxMap_Bit_edit,   3, 24);
ZOOM_EDIT_HANDLER(Fx_FLT_CtxMap_Level_edit, 4, 28);

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
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    int slot = ctxmap_scaled_index(params[CTXMAP_SLOT_SLOT], CTXMAP_SLOT_UI_MAX);
    int bit = ctxmap_scaled_index(params[CTXMAP_BIT_SLOT], CTXMAP_BIT_UI_MAX);
    float level = zoom_clamp01(params[CTXMAP_LEVEL_SLOT] * ZOOM_PARAM_RAW_TO_NORM);

    unsigned int word = ctx[(unsigned int)slot & 15u];
    unsigned int bit_on = (word >> ((unsigned int)bit & 31u)) & 1u;
    float amp = bit_on ? (0.01f + (level * 0.06f)) : 0.0f;

    int i;
    for (i = 0; i < 16; i++) {
        float tone;

        gPhase += 1u;
        tone = (gPhase & 32u) ? amp : -amp;
        outBuf[i] += tone * params[0];
    }
}
