/*
 * ctxnib.c
 *
 * Nibble mapper for Zoom Multistomp ctx[] reverse engineering.
 *
 * CtxGate proved that stereo panning is a usable observation channel for raw
 * ctx[Slot].Bit values, but sweeping all 32 bits by hand is error-prone. This
 * probe reads ctx[Slot], selects one 4-bit nibble, and repeats a timed pattern:
 *
 *   sync segment: center/loud
 *   bit 0: left = 0, right = 1
 *   bit 1: left = 0, right = 1
 *   bit 2: left = 0, right = 1
 *   bit 3: left = 0, right = 1
 *   gap segments: center/quiet
 *
 * It uses the input signal rather than generating an oscillator. The selected
 * ctx word is read as a raw 32-bit value and is never dereferenced.
 */

#include <stdint.h>

#include "ctxnib_params.h"

#pragma CODE_SECTION(Fx_FLT_CtxNib, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#pragma DATA_SECTION(gPhase, ".fardata")
static unsigned int gPhase = 0;

static unsigned int select_slot(float raw)
{
    unsigned int slot = 0u;

    if (raw >= 0.0043750f) slot = 1u;
    if (raw >= 0.0131250f) slot = 2u;
    if (raw >= 0.0218750f) slot = 3u;
    if (raw >= 0.0306250f) slot = 4u;
    if (raw >= 0.0393750f) slot = 5u;
    if (raw >= 0.0481250f) slot = 6u;
    if (raw >= 0.0568750f) slot = 7u;
    if (raw >= 0.0656250f) slot = 8u;
    if (raw >= 0.0743750f) slot = 9u;
    if (raw >= 0.0831250f) slot = 10u;
    if (raw >= 0.0918750f) slot = 11u;
    if (raw >= 0.1006250f) slot = 12u;
    if (raw >= 0.1093750f) slot = 13u;
    if (raw >= 0.1181250f) slot = 14u;
    if (raw >= 0.1268750f) slot = 15u;

    return slot;
}

static unsigned int select_nib(float raw)
{
    unsigned int nib = 0u;

    if (raw >= 0.0100000f) nib = 1u;
    if (raw >= 0.0300000f) nib = 2u;
    if (raw >= 0.0500000f) nib = 3u;
    if (raw >= 0.0700000f) nib = 4u;
    if (raw >= 0.0900000f) nib = 5u;
    if (raw >= 0.1100000f) nib = 6u;
    if (raw >= 0.1300000f) nib = 7u;

    return nib;
}

void Fx_FLT_CtxNib(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int slot = select_slot(params[CTXNIB_SLOT_SLOT]);
    unsigned int nib = select_nib(params[CTXNIB_NIB_SLOT]);
    unsigned int word = ctx[slot & 15u];
    unsigned int value = (word >> ((nib & 7u) << 2)) & 15u;

    unsigned int seg = (gPhase >> 13) & 7u;
    float gainL = 0.20f;
    float gainR = 0.20f;

    if (seg == 0u) {
        gainL = 1.50f;
        gainR = 1.50f;
    } else if (seg <= 4u) {
        unsigned int bit_on = (value >> (seg - 1u)) & 1u;
        gainL = bit_on ? 0.05f : 2.00f;
        gainR = bit_on ? 2.00f : 0.05f;
    }

    int i;
    for (i = 0; i < 8; i++) {
        gPhase += 1u;
        outBuf[i] += fxBuf[i] * gainL;
    }
    for (i = 8; i < 16; i++) {
        gPhase += 1u;
        outBuf[i] += fxBuf[i] * gainR;
    }
}
