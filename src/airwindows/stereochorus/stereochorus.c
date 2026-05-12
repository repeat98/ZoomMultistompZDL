/*
 * StereoChorus by Chris Johnson (airwindows) - MIT licence
 * Zoom Multistomp ABI experiment.
 *
 * The source plugin uses two 65536-sample int delay lines. That is far too
 * large for the current custom-ZDL state ABI, so this release uses a tiny
 * initialized ring buffer. It is not the full Airwindows algorithm yet, but it
 * is a real modulated delay instead of the earlier near-dry smoke test.
 *
 * This is NOT a release-quality Airwindows port: it does not run the exact
 * source DSP. Keep it as an ABI/state experiment until the real delay-line
 * state strategy is solved.
 */

#include <stdint.h>

#include "../common/zoom_params.h"
#include "stereochorus_params.h"

#pragma CODE_SECTION(Fx_MOD_StChorus, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))
#define CHORUS_BUF 56

#pragma DATA_SECTION(delayL, ".fardata")
static float delayL[CHORUS_BUF] = { 0.0000001f };

#pragma DATA_SECTION(delayR, ".fardata")
static float delayR[CHORUS_BUF] = { -0.0000001f };

#pragma DATA_SECTION(writePos, ".fardata")
static int writePos = 0;

#pragma DATA_SECTION(lfoPhase, ".fardata")
static int lfoPhase = 0;

void Fx_MOD_StChorus(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    float pSpeed = zoom_param_norm(params[STCHORUS_SPEED_SLOT], STCHORUS_SPEED_DEFAULT_NORM);
    float pDepth = zoom_param_norm(params[STCHORUS_DEPTH_SLOT], STCHORUS_DEPTH_DEFAULT_NORM);

    if (pDepth <= 0.0001f) return;

    /* Hardware-safe beta core:
     * - tiny initialized .fardata only
     * - no stack arrays
     * - no division / runtime helper calls
     * - no sin/log/pow
     *
     * The real Airwindows code uses a huge int delay line plus sine LFO. This
     * keeps the same Speed/Depth controls but compresses the delay span into
     * 56 samples so it is safe to probe on hardware. */
    int phaseStep = 1 + (int)(pSpeed * 7.0f);
    int depthSpan = 1 + (int)(pDepth * 46.0f);
    float wet = 0.18f + pDepth * 0.72f;
    float dry = 1.0f - wet * 0.42f;
    float cross = pDepth * 0.18f;

    int i;
    for (i = 0; i < 8; i++) {
        float curL = fxBuf[i];
        float curR = fxBuf[i + 8];

        int triL = lfoPhase & 63;
        int triR = (lfoPhase + 21) & 63;
        if (triL > 31) triL = 63 - triL;
        if (triR > 31) triR = 63 - triR;

        int dL = 2 + ((triL * depthSpan) >> 5);
        int dR = 2 + ((triR * depthSpan) >> 5);

        int readL = writePos - dL;
        int readR = writePos - dR;
        if (readL < 0) readL += CHORUS_BUF;
        if (readR < 0) readR += CHORUS_BUF;

        float tapL = delayL[readL];
        float tapR = delayR[readR];

        delayL[writePos] = curL;
        delayR[writePos] = curR;

        fxBuf[i] = curL * dry + tapL * wet + tapR * cross;
        fxBuf[i + 8] = curR * dry + tapR * wet + tapL * cross;

        writePos++;
        if (writePos >= CHORUS_BUF) writePos = 0;

        lfoPhase += phaseStep;
        lfoPhase &= 63;
    }
}
