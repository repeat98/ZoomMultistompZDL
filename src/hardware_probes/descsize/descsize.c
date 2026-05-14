/*
 * descsize.c
 *
 * Fixed-threshold size probe for the ctx[3] large-buffer descriptor.
 *
 * Arm off: pass-through, no ctx[3] dereference.
 * Arm on: read ctx[3][0..2]. If the descriptor is plausible and its byte
 * length meets DESCSIZE_THRESHOLD_BYTES, report success as stereo wobble using
 * the already proven ctx[2]+0x18 counter. Otherwise pass through.
 */

#include <stdint.h>

#include "descsize_params.h"

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define DESCSIZE_DO_PRAGMA(x) _Pragma(#x)
#define DESCSIZE_EXPAND_PRAGMA(x) DESCSIZE_DO_PRAGMA(x)
#define DESCSIZE_CODE_SECTION(func) DESCSIZE_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))

#ifndef DESCSIZE_AUDIO_FUNC
#define DESCSIZE_AUDIO_FUNC Fx_FLT_Dsz512K
#endif

#ifndef DESCSIZE_THRESHOLD_BYTES
#define DESCSIZE_THRESHOLD_BYTES 524288u
#endif

#define DESCSIZE_REPORT_WORD 18u

DESCSIZE_CODE_SECTION(DESCSIZE_AUDIO_FUNC)
void DESCSIZE_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    unsigned int arm = (params[DESCSIZE_ARM_SLOT] >= 0.001f) ? 1u : 0u;
    unsigned int success = 0u;

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
        if (bytes < 96u || span < 96u) {
            plausible = 0u;
        }
        if (bytes > 0x00800000u || span > 0x00800000u) {
            plausible = 0u;
        }
        if (span < bytes) {
            plausible = 0u;
        }
        if (plausible != 0u && bytes >= (uintptr_t)DESCSIZE_THRESHOLD_BYTES) {
            success = 1u;
        }
    }

    float gainL = 1.0f;
    float gainR = 1.0f;

    if (success != 0u) {
        unsigned int *smallState = (unsigned int *)((uintptr_t)ctx[2] + 0x18u);
        unsigned int phase = smallState[DESCSIZE_REPORT_WORD] + 1u;
        smallState[DESCSIZE_REPORT_WORD] = phase;
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
