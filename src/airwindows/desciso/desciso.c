/*
 * desciso.c
 *
 * Instance-isolation probe for ctx[3] descriptor base memory.
 *
 * Arm off: pass-through, no ctx[3] dereference.
 * Arm on: validate ctx[3], then stamp descriptor memory with a role-specific
 * magic. If the opposite role's stamp is already present, report it as stereo
 * wobble. Use two instances of the same effect with opposite Role settings.
 */

#include <stdint.h>

#include "desciso_params.h"

#pragma CODE_SECTION(Fx_FLT_DescIso, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define DESCISO_ROLE_A_MAGIC 0x13579BDFu
#define DESCISO_ROLE_B_MAGIC 0x2468ACE0u

void Fx_FLT_DescIso(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int arm = (params[DESCISO_ARM_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int role = (params[DESCISO_ROLE_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int magic = (role != 0u) ? DESCISO_ROLE_B_MAGIC : DESCISO_ROLE_A_MAGIC;
    unsigned int foreign = 0u;
    unsigned int phase = 0u;

    if (arm != 0u) {
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
        if (bytes < 32u || span < 32u) {
            plausible = 0u;
        }
        if (bytes > 0x00800000u || span > 0x00800000u) {
            plausible = 0u;
        }
        if (span < bytes) {
            plausible = 0u;
        }

        if (plausible != 0u) {
            unsigned int *mem = (unsigned int *)base;
            unsigned int prev = mem[0];
            phase = mem[1] + 1u;
            mem[0] = magic;
            mem[1] = phase;

            if (prev != 0u && prev != magic) {
                foreign = 1u;
            }
        }
    }

    float gainL = 1.0f;
    float gainR = 1.0f;
    if (foreign != 0u) {
        if ((phase & 0x20u) != 0u) {
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
        outBuf[i + 8] += fxBuf[i + 8] * gainR;
    }
}
