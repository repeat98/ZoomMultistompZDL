/*
 * ctxgate.c
 *
 * Input-based ctx[] bit mapper for Zoom Multistomp hardware.
 *
 * ParamTap proved the two stock LineSel edit handlers can update params[5]
 * and params[6]. CtxMap's generated oscillator was ambiguous, so this probe
 * avoids generated audio entirely. Feed guitar or another signal through it:
 *
 *   selected bit = 0 -> quiet input pass-through
 *   selected bit = 1 -> louder input pass-through
 *
 * The selected ctx word is read as a raw 32-bit value and is never
 * dereferenced.
 */

#include <stdint.h>

#include "ctxgate_params.h"

#pragma CODE_SECTION(Fx_FLT_CtxGate, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

void Fx_FLT_CtxGate(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    float slotRaw = params[CTXGATE_SLOT_SLOT];
    float bitRaw = params[CTXGATE_BIT_SLOT];
    unsigned int slot = 0u;
    unsigned int bit = 0u;

    /*
     * Avoid float-to-int conversion helpers in the selector path. The previous
     * build sounded like it was always checking the same condition, so this
     * ladder uses only float comparisons and integer assignments.
     */
    if (slotRaw >= 0.0043750f) slot = 1u;
    if (slotRaw >= 0.0131250f) slot = 2u;
    if (slotRaw >= 0.0218750f) slot = 3u;
    if (slotRaw >= 0.0306250f) slot = 4u;
    if (slotRaw >= 0.0393750f) slot = 5u;
    if (slotRaw >= 0.0481250f) slot = 6u;
    if (slotRaw >= 0.0568750f) slot = 7u;
    if (slotRaw >= 0.0656250f) slot = 8u;
    if (slotRaw >= 0.0743750f) slot = 9u;
    if (slotRaw >= 0.0831250f) slot = 10u;
    if (slotRaw >= 0.0918750f) slot = 11u;
    if (slotRaw >= 0.1006250f) slot = 12u;
    if (slotRaw >= 0.1093750f) slot = 13u;
    if (slotRaw >= 0.1181250f) slot = 14u;
    if (slotRaw >= 0.1268750f) slot = 15u;

    if (bitRaw >= 0.0022581f) bit = 1u;
    if (bitRaw >= 0.0067742f) bit = 2u;
    if (bitRaw >= 0.0112903f) bit = 3u;
    if (bitRaw >= 0.0158065f) bit = 4u;
    if (bitRaw >= 0.0203226f) bit = 5u;
    if (bitRaw >= 0.0248387f) bit = 6u;
    if (bitRaw >= 0.0293548f) bit = 7u;
    if (bitRaw >= 0.0338710f) bit = 8u;
    if (bitRaw >= 0.0383871f) bit = 9u;
    if (bitRaw >= 0.0429032f) bit = 10u;
    if (bitRaw >= 0.0474194f) bit = 11u;
    if (bitRaw >= 0.0519355f) bit = 12u;
    if (bitRaw >= 0.0564516f) bit = 13u;
    if (bitRaw >= 0.0609677f) bit = 14u;
    if (bitRaw >= 0.0654839f) bit = 15u;
    if (bitRaw >= 0.0700000f) bit = 16u;
    if (bitRaw >= 0.0745161f) bit = 17u;
    if (bitRaw >= 0.0790323f) bit = 18u;
    if (bitRaw >= 0.0835484f) bit = 19u;
    if (bitRaw >= 0.0880645f) bit = 20u;
    if (bitRaw >= 0.0925806f) bit = 21u;
    if (bitRaw >= 0.0970968f) bit = 22u;
    if (bitRaw >= 0.1016129f) bit = 23u;
    if (bitRaw >= 0.1061290f) bit = 24u;
    if (bitRaw >= 0.1106452f) bit = 25u;
    if (bitRaw >= 0.1151613f) bit = 26u;
    if (bitRaw >= 0.1196774f) bit = 27u;
    if (bitRaw >= 0.1241935f) bit = 28u;
    if (bitRaw >= 0.1287097f) bit = 29u;
    if (bitRaw >= 0.1332258f) bit = 30u;
    if (bitRaw >= 0.1377419f) bit = 31u;

    unsigned int word = ctx[slot & 15u];
    unsigned int bit_on = (word >> (bit & 31u)) & 1u;
    float gain = bit_on ? 1.25f : 0.10f;

    int i;
    for (i = 0; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gain;
    }
}
