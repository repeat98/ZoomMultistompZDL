/*
 * reel.c -- Reel: light, stable tape saturation, MS-70CDR.
 *
 * A deliberately CHEAP, rock-solid replacement for the upstream TapeHack
 * (which freezes via its object-defined asm edit handler). No buffer, no
 * modulation, no math lib, tiny state, 2 knobs on the proven LineSel path:
 *   Drive (params[5]) - input drive into the tape soft-clip
 *   Level (params[6]) - output level
 * Tape tone roll-off is baked.
 *
 * DSP: pre-gain -> asymmetric cubic soft-clip (tape harmonics + compression)
 * -> one-pole high-cut (tape bandwidth) -> output level. A few ops/sample, so
 * it's DSP-light and friendly to chain. ctx[11]/ctx[12] magic shuttle kept.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "reel_params.h"

#ifndef REEL_AUDIO_FUNC
#define REEL_AUDIO_FUNC Fx_DYN_Reel
#endif

#define REEL_DO_PRAGMA(x) _Pragma(#x)
#define REEL_EXPAND_PRAGMA(x) REEL_DO_PRAGMA(x)
#define REEL_CODE_SECTION(f) REEL_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

REEL_CODE_SECTION(REEL_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define REEL_MAGIC   0x5245454Cu   /* 'REEL' */
#define REEL_VERSION 1u

#define REEL_BIAS    0.10f         /* asymmetry -> even harmonics */
#define REEL_TONE    0.42f         /* baked high-cut (tape bandwidth) */

typedef struct ReelState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t pad;
    float lpL, lpR;
} ReelState;

static inline float reel_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

void REEL_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u) return;
    if (end - base < (uintptr_t)sizeof(ReelState)) return;

    ReelState *st = (ReelState *)base;
    if (st->magic != REEL_MAGIC || st->version != REEL_VERSION || !st->initialized) {
        st->magic = REEL_MAGIC;
        st->version = REEL_VERSION;
        st->lpL = st->lpR = 0.0f;
        st->initialized = 1u;
    }

    float drive = zoom_param_norm01(params[REEL_DRIVE_SLOT], REEL_DRIVE_DEFAULT_NORM);
    float level = zoom_param_norm01(params[REEL_LEVEL_SLOT], REEL_LEVEL_DEFAULT_NORM);
    float driveGain = 1.0f + drive * 6.0f;
    float outGain = 0.3f + level * 1.2f;
    float biasOut = reel_soft(REEL_BIAS);

    float lpL = st->lpL, lpR = st->lpR;
    int i;
    for (i = 0; i < 8; i++) {
        float inL = fxBuf[i];
        float inR = fxBuf[i + 8];

        float sL = reel_soft(inL * driveGain + REEL_BIAS) - biasOut;
        float sR = reel_soft(inR * driveGain + REEL_BIAS) - biasOut;
        lpL += REEL_TONE * (sL - lpL);
        lpR += REEL_TONE * (sR - lpR);

        fxBuf[i]     = lpL * outGain;
        fxBuf[i + 8] = lpR * outGain;
    }

    st->lpL = lpL;
    st->lpR = lpR;
}
