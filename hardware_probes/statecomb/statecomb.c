/*
 * statecomb.c
 *
 * Tiny DSP-history probe for the proven ctx[2] + 0x18 host state block.
 *
 * Arm off: pass-through, no ctx[2] dereference.
 * Arm on: words 0..15 hold a mono 16-sample feedback comb ring, and word 18
 * holds the ring index. This should color audio if the host state persists
 * across callbacks. If state is reset every callback, it should mostly behave
 * like pass-through.
 */

#include <stdint.h>

#include "statecomb_params.h"

#pragma CODE_SECTION(Fx_FLT_StateComb, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define STATECOMB_RING_MASK 15u
#define STATECOMB_INDEX_WORD 18u

void Fx_FLT_StateComb(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int arm = (params[STATECOMB_ARM_SLOT] >= 0.001f) ? 1u : 0u;
    float mix = params[STATECOMB_MIX_SLOT];
    if (!(mix > 0.0f && mix < 1.25f)) {
        mix = 0.5f;
    }

    if (arm == 0u) {
        int j;
        for (j = 0; j < 8; j++) {
            outBuf[j] += fxBuf[j];
            outBuf[j + 8] += fxBuf[j + 8];
        }
        return;
    }

    unsigned int *state = (unsigned int *)((uintptr_t)ctx[2] + 0x18u);
    unsigned int idx = state[STATECOMB_INDEX_WORD] & STATECOMB_RING_MASK;

    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];
        float mono = (inL + inR) * 0.5f;
        union {
            float f;
            unsigned int u;
        } bits;
        bits.u = state[idx];
        float delayed = bits.f;
        if (!(delayed > -4.0f && delayed < 4.0f)) {
            delayed = 0.0f;
        }
        if (delayed > 1.5f) {
            delayed = 1.5f;
        }
        if (delayed < -1.5f) {
            delayed = -1.5f;
        }

        float store = mono + delayed * 0.55f;
        if (!(store > -4.0f && store < 4.0f)) {
            store = 0.0f;
        }
        if (store > 1.5f) {
            store = 1.5f;
        }
        if (store < -1.5f) {
            store = -1.5f;
        }

        bits.f = store;
        state[idx] = bits.u;
        idx = (idx + 1u) & STATECOMB_RING_MASK;

        outBuf[i] += inL * 0.72f + delayed * mix * 0.65f;
        outBuf[i + 8] += inR * 0.72f + delayed * mix * 0.65f;
    }

    state[STATECOMB_INDEX_WORD] = idx;
}
