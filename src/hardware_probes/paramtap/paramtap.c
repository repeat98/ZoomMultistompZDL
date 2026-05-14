/*
 * paramtap.c
 *
 * Small hardware probe for Zoom Multistomp parameter plumbing.
 *
 * It intentionally does not read unknown ctx fields and does not generate
 * oscillator audio. Feed guitar or any input signal through the pedal:
 *
 *   TapA should change the left-half block gain.
 *   TapB should change the right-half block gain.
 *
 * Because the buffers are laid out as 8 L samples followed by 8 R samples,
 * this gives us an audible way to prove whether params[5] and params[6] are
 * actually changing before we trust those params for CtxMap slot/bit mapping.
 */

#include <stdint.h>

#include "paramtap_params.h"

#pragma CODE_SECTION(Fx_FLT_ParamTap, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

void Fx_FLT_ParamTap(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /*
     * Stock edit handlers write small raw floats, roughly 0..0.14. Keep this
     * scaling simple and intentionally large enough to hear on hardware.
     */
    float gainA = 0.10f + (params[PARAMTAP_TAPA_SLOT] * 10.0f);
    float gainB = 0.10f + (params[PARAMTAP_TAPB_SLOT] * 10.0f);

    int i;
    for (i = 0; i < 8; i++) {
        outBuf[i] += fxBuf[i] * gainA;
    }
    for (i = 8; i < 16; i++) {
        outBuf[i] += fxBuf[i] * gainB;
    }
}
