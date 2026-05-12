/*
 * stateping.c
 *
 * Conservative persistence probe for the stock ctx[2] state-block pattern.
 *
 * Arm10 = 0 and Arm18 = 0 is pass-through and does not dereference ctx[2].
 * Arm10 = 1 tests ctx[2] + 0x10, matching DELAY's derived state block.
 * Arm18 = 1 tests ctx[2] + 0x18, matching STCHO/TAPEECHO's derived block.
 * STATEPING_FIXED_WORD selects which 32-bit word inside that derived block to
 * increment. Interactive word selection froze hardware, so depth tests are
 * separate fixed-word builds.
 *
 * When armed, this probe increments one selected word and uses a counter bit
 * to pan the input. Persistent writable state should create an audible
 * left/right wobble. Non-persistent/reset state should stay mostly fixed.
 */

#include <stdint.h>

#include "stateping_params.h"

#pragma CODE_SECTION(Fx_FLT_StatePing, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#ifndef STATEPING_FIXED_WORD
#define STATEPING_FIXED_WORD 0u
#endif

void Fx_FLT_StatePing(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /*
     * ParamTap showed stock edit handlers write small raw floats, not full
     * 0.0/1.0 normalized switch values. Anything clearly above zero counts as
     * armed.
     */
    unsigned int arm10 = (params[STATEPING_ARM10_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int arm18 = (params[STATEPING_ARM18_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int word = (unsigned int)STATEPING_FIXED_WORD;
    float gainL = 1.0f;
    float gainR = 1.0f;

    if (arm10 != 0u || arm18 != 0u) {
        uintptr_t state_addr = (uintptr_t)ctx[2];
        state_addr += (arm18 != 0u) ? 0x18u : 0x10u;

        unsigned int *state = (unsigned int *)state_addr;
        unsigned int next = state[word] + 1u;
        state[word] = next;

        if ((next & 0x20u) != 0u) {
            gainL = 0.08f;
            gainR = 1.80f;
        } else {
            gainL = 1.80f;
            gainR = 0.08f;
        }
    }

    int i;
    for (i = 0; i < 8; i++) {
        outBuf[i] += fxBuf[i] * gainL;
    }
    for (i = 8; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gainR;
    }
}
