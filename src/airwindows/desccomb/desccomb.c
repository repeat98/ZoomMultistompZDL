/*
 * desccomb.c
 *
 * Staged probe for the stock ctx[3] descriptor shape.
 *
 * Stock delay/chorus audio code treats ctx[3] as a descriptor:
 *   desc[0] = base pointer
 *   desc[1] = end pointer
 *   desc[2] = wrap/span
 *
 * Arm off: pass-through, no ctx[3] dereference.
 * Arm on, UseBuf off: read descriptor only. If it looks plausible, report that
 * with stereo wobble using the already proven ctx[2]+0x18 counter.
 * Arm on, UseBuf on: use descriptor base memory as a tiny 16-sample comb ring.
 */

#include <stdint.h>

#include "desccomb_params.h"

#pragma CODE_SECTION(Fx_FLT_DescComb, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define DESCCOMB_RING_MASK 15u
#define DESCCOMB_INDEX_WORD 16u
#define DESCCOMB_REPORT_WORD 18u

void Fx_FLT_DescComb(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int arm = (params[DESCCOMB_ARM_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int useBuf = (params[DESCCOMB_USEBUF_SLOT] >= 0.001f) ? 1u : 0u;

    if (arm == 0u) {
        int j;
        for (j = 0; j < 8; j++) {
            outBuf[j] += fxBuf[j];
            outBuf[j + 8] += fxBuf[j + 8];
        }
        return;
    }

    unsigned int *desc = ZDL_PTR(unsigned int *, ctx[3]);
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end = (uintptr_t)desc[1];
    unsigned int span = desc[2];
    uintptr_t bytes = end - base;
    unsigned int plausible = 1u;

    if (base == 0u || end <= base) {
        plausible = 0u;
    }
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) {
        plausible = 0u;
    }
    if (bytes < 96u || span < 96u) {
        plausible = 0u;
    }
    if (bytes > 0x00800000u || span > 0x00800000u) {
        plausible = 0u;
    }
    if (span < bytes) {
        plausible = 0u;
    }

    if (plausible == 0u) {
        int k;
        for (k = 0; k < 8; k++) {
            outBuf[k] += fxBuf[k];
            outBuf[k + 8] += fxBuf[k + 8];
        }
        return;
    }

    if (useBuf == 0u) {
        unsigned int *smallState = (unsigned int *)((uintptr_t)ctx[2] + 0x18u);
        unsigned int phase = smallState[DESCCOMB_REPORT_WORD] + 1u;
        float gainL;
        float gainR;
        smallState[DESCCOMB_REPORT_WORD] = phase;

        if ((phase & 0x20u) != 0u) {
            gainL = 0.08f;
            gainR = 1.80f;
        } else {
            gainL = 1.80f;
            gainR = 0.08f;
        }

        int n;
        for (n = 0; n < 8; n++) {
            outBuf[n] += fxBuf[n] * gainL;
            outBuf[n + 8] += fxBuf[n + 8] * gainR;
        }
        return;
    }

    unsigned int *ring = (unsigned int *)base;
    unsigned int idx = ring[DESCCOMB_INDEX_WORD] & DESCCOMB_RING_MASK;

    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];
        float mono = (inL + inR) * 0.5f;
        union {
            float f;
            unsigned int u;
        } bits;
        bits.u = ring[idx];
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
        ring[idx] = bits.u;
        idx = (idx + 1u) & DESCCOMB_RING_MASK;

        outBuf[i] += inL * 0.72f + delayed * 0.40f;
        outBuf[i + 8] += inR * 0.72f + delayed * 0.40f;
    }

    ring[DESCCOMB_INDEX_WORD] = idx;
}
