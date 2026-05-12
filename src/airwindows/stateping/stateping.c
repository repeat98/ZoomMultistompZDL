/*
 * stateping.c
 *
 * Conservative persistence probe for the stock ctx[2] state-block pattern.
 *
 * Arm10 = 0 and Arm18 = 0 is pass-through and does not dereference ctx[2].
 * Arm10 = 1 tests ctx[2] + 0x10, matching DELAY's derived state block.
 * Arm18 = 1 tests ctx[2] + 0x18, matching STCHO/TAPEECHO's derived block.
 * Word selects which 32-bit word inside that derived block to increment.
 * Word 31 froze hardware in testing, so this build caps the selector at 19.
 *
 * When armed, this probe increments one selected word and uses a counter bit
 * to pan the input. Persistent writable state should create an audible
 * left/right wobble. Non-persistent/reset state should stay mostly fixed.
 */

#include <stdint.h>

#include "stateping_params.h"

#pragma CODE_SECTION(Fx_FLT_StatePing, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

static unsigned int select_word(float word_raw)
{
    unsigned int word = 0u;
    if (word_raw >= 0.0022581f) word = 1u;
    if (word_raw >= 0.0067742f) word = 2u;
    if (word_raw >= 0.0112903f) word = 3u;
    if (word_raw >= 0.0158065f) word = 4u;
    if (word_raw >= 0.0203226f) word = 5u;
    if (word_raw >= 0.0248387f) word = 6u;
    if (word_raw >= 0.0293548f) word = 7u;
    if (word_raw >= 0.0338710f) word = 8u;
    if (word_raw >= 0.0383871f) word = 9u;
    if (word_raw >= 0.0429032f) word = 10u;
    if (word_raw >= 0.0474194f) word = 11u;
    if (word_raw >= 0.0519355f) word = 12u;
    if (word_raw >= 0.0564516f) word = 13u;
    if (word_raw >= 0.0609677f) word = 14u;
    if (word_raw >= 0.0654839f) word = 15u;
    if (word_raw >= 0.0700000f) word = 16u;
    if (word_raw >= 0.0745161f) word = 17u;
    if (word_raw >= 0.0790323f) word = 18u;
    if (word_raw >= 0.0835484f) word = 19u;
    return word;
}

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
    unsigned int word = select_word(params[STATEPING_WORD_SLOT]);
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
