/*
 * stateiso.c
 *
 * Instance-isolation probe for the proven ctx[2] + 0x18 state block.
 *
 * With Arm off, this is pass-through and does not dereference ctx[2].
 * With Arm on, each variant writes STATEISO_MAGIC into word 19 of the
 * ctx[2] + 0x18 block. If another variant's magic is already there, the probe
 * reports that foreign stamp as stereo wobble.
 *
 * Expected interpretation:
 * - StateIsoA alone should settle to centered pass-through after the first
 *   callback, because it only sees its own stamp.
 * - StateIsoA + StateIsoB in separate slots should remain centered if the
 *   host state block is per instance.
 * - StateIsoA + StateIsoB should wobble continuously if both slots share the
 *   same ctx[2] + 0x18 block.
 */

#include <stdint.h>

#include "stateiso_params.h"

#pragma CODE_SECTION(Fx_FLT_StateIso, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#ifndef STATEISO_MAGIC
#define STATEISO_MAGIC 0x13579BDFu
#endif

#define STATEISO_PHASE_WORD 18u
#define STATEISO_STAMP_WORD 19u

void Fx_FLT_StateIso(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int arm = (params[STATEISO_ARM_SLOT] >= 0.001f) ? 1u : 0u;
    float gainL = 1.0f;
    float gainR = 1.0f;

    if (arm != 0u) {
        uintptr_t state_addr = (uintptr_t)ctx[2] + 0x18u;
        unsigned int *state = (unsigned int *)state_addr;
        unsigned int prev = state[STATEISO_STAMP_WORD];
        unsigned int phase = state[STATEISO_PHASE_WORD] + 1u;

        state[STATEISO_PHASE_WORD] = phase;
        state[STATEISO_STAMP_WORD] = (unsigned int)STATEISO_MAGIC;

        if (prev != 0u && prev != (unsigned int)STATEISO_MAGIC) {
            if ((phase & 0x20u) != 0u) {
                gainL = 0.08f;
                gainR = 1.80f;
            } else {
                gainL = 1.80f;
                gainR = 0.08f;
            }
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
