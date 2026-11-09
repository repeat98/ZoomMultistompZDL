/*
 * matprobe.c -- does _init materialize params on load? A DISPOSABLE test effect.
 *
 * Nothing here is meant to be musical. It exists so the materialization _init can
 * be tested on hardware without risking an effect anyone plays: a wrong _init
 * freezes the DSP on boot and needs an Effect Manager rewrite to recover, and
 * that has now happened twice (InitProbe stage 3 in May, and v1 of this on
 * 2026-09-07). Freeze THIS and you lose nothing.
 *
 * Two knobs, and the test is meant to be unmistakable by ear:
 *   Gain  (params[5]) - output level, 0..1. At its DEFAULT it is SILENT.
 *   Tone  (params[6]) - one-pole low-pass, dark..bright.
 *
 * Gain defaulting to silence is the whole trick. zoom_param_norm01 returns the
 * DEFAULT when a param reads zero, so:
 *   - params zeroed on load  -> Gain falls back to its default -> SILENCE
 *   - params materialized    -> Gain is whatever you dialled   -> SOUND
 * so "did it work" is audible from across the room, with no knob-watching and
 * nothing to interpret.
 *
 * Safe-DSP: no switch, no CALLs, no divide, no static arrays, denormals flushed.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "matprobe_params.h"

#ifndef MATPROBE_AUDIO_FUNC
#define MATPROBE_AUDIO_FUNC Fx_DLY_MatProb
#endif

#define MP_DO_PRAGMA(x) _Pragma(#x)
#define MP_EXPAND_PRAGMA(x) MP_DO_PRAGMA(x)
#define MP_CODE_SECTION(f) MP_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

MP_CODE_SECTION(MATPROBE_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define MP_MAGIC   0x4D415450u   /* 'MATP' */
#define MP_VERSION 1u
#define MP_DENORM  1.0e-18f

typedef struct MatProbeState {
    uint32_t magic, version, initialized, pad;
    float lpL, lpR;
} MatProbeState;

void MATPROBE_AUDIO_FUNC(unsigned int *ctx)
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
    if (base + sizeof(MatProbeState) > end) return;

    MatProbeState *st = (MatProbeState *)base;
    if (st->magic != MP_MAGIC || st->version != MP_VERSION || !st->initialized) {
        st->magic = MP_MAGIC; st->version = MP_VERSION;
        st->lpL = st->lpR = 0.0f;
        st->initialized = 1u;
    }

    /* Gain's DEFAULT is 0: unmaterialized params fall back to it and the effect
     * is silent. That silence IS the failure signal. */
    float g  = zoom_param_norm01(params[MATPROBE_GAIN_SLOT], MATPROBE_GAIN_DEFAULT_NORM);
    float tn = zoom_param_norm01(params[MATPROBE_TONE_SLOT], MATPROBE_TONE_DEFAULT_NORM);
    float k  = 0.02f + tn * 0.9f;

    float lpL = st->lpL, lpR = st->lpR;
    int i;
    for (i = 0; i < 8; i++) {
        float l = fxBuf[i], r = fxBuf[i + 8];
        lpL += k * (l - lpL);
        lpR += k * (r - lpR);
        if (lpL < MP_DENORM && lpL > -MP_DENORM) lpL = 0.0f;
        if (lpR < MP_DENORM && lpR > -MP_DENORM) lpR = 0.0f;
        fxBuf[i]     = lpL * g;
        fxBuf[i + 8] = lpR * g;
    }
    st->lpL = lpL; st->lpR = lpR;
}
