/*
 * Galactic by Chris Johnson (airwindows) - MIT licence.
 * Zoom Multistomp port candidate.
 *
 * Source reference:
 *   airwindows-ref/plugins/LinuxVST/src/Galactic/GalacticProc.cpp
 *
 * This keeps the original Galactic feedback-delay topology, converted from
 * double to float and stored in the host-provided ctx[3] arena. The pedal is
 * assumed to run at 44.1 kHz, so overallscale = 1.0 and cycleEnd = 1. The
 * Airwindows floating-point dither tail is omitted, matching the other Zoom
 * Airwindows ports.
 */

#include <stdint.h>

#include "../common/zoom_params.h"
#include "galactic_params.h"

#ifndef GALACTIC_AUDIO_FUNC
#define GALACTIC_AUDIO_FUNC Fx_REV_Galactic
#endif

#define GALACTIC_DO_PRAGMA(x) _Pragma(#x)
#define GALACTIC_EXPAND_PRAGMA(x) GALACTIC_DO_PRAGMA(x)
#define GALACTIC_CODE_SECTION(func) GALACTIC_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))
GALACTIC_CODE_SECTION(GALACTIC_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define GALACTIC_MAGIC 0x47414C41u
#define GALACTIC_VERSION 1u
#define GALACTIC_CLEAR_STEP 512u

#define GAL_A_LEN 9700
#define GAL_B_LEN 6000
#define GAL_C_LEN 2320
#define GAL_D_LEN 940
#define GAL_E_LEN 15220
#define GAL_F_LEN 8460
#define GAL_G_LEN 4540
#define GAL_H_LEN 3200
#define GAL_I_LEN 6480
#define GAL_J_LEN 3660
#define GAL_K_LEN 1720
#define GAL_L_LEN 680
#define GAL_M_LEN 3111

#define GAL_PARAM_MISSING(raw) (!((raw) >= 0.0f && (raw) <= 100.0f))
#define GAL_PARAM_NORM(raw, fallback_norm) zoom_param_norm01((raw), (fallback_norm))

#define GAL_READ(buf, count, delay) ((buf)[(count) - (((count) > (delay)) ? ((delay) + 1) : 0)])

typedef struct GalacticState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    float iirAL;
    float iirBL;
    float iirAR;
    float iirBR;

    float aIL[GAL_I_LEN];
    float aJL[GAL_J_LEN];
    float aKL[GAL_K_LEN];
    float aLL[GAL_L_LEN];
    float aIR[GAL_I_LEN];
    float aJR[GAL_J_LEN];
    float aKR[GAL_K_LEN];
    float aLR[GAL_L_LEN];

    float aAL[GAL_A_LEN];
    float aBL[GAL_B_LEN];
    float aCL[GAL_C_LEN];
    float aDL[GAL_D_LEN];
    float aAR[GAL_A_LEN];
    float aBR[GAL_B_LEN];
    float aCR[GAL_C_LEN];
    float aDR[GAL_D_LEN];

    float aEL[GAL_E_LEN];
    float aFL[GAL_F_LEN];
    float aGL[GAL_G_LEN];
    float aHL[GAL_H_LEN];
    float aER[GAL_E_LEN];
    float aFR[GAL_F_LEN];
    float aGR[GAL_G_LEN];
    float aHR[GAL_H_LEN];

    float aML[GAL_M_LEN];
    float aMR[GAL_M_LEN];

    float feedbackAL;
    float feedbackBL;
    float feedbackCL;
    float feedbackDL;
    float feedbackAR;
    float feedbackBR;
    float feedbackCR;
    float feedbackDR;

    float lastRefL[7];
    float lastRefR[7];
    float thunderL;
    float thunderR;
    float vibM;
    float oldfpd;

    int countA;
    int countB;
    int countC;
    int countD;
    int countE;
    int countF;
    int countG;
    int countH;
    int countI;
    int countJ;
    int countK;
    int countL;
    int countM;
    int cycle;

    uint32_t fpdL;
    uint32_t fpdR;
} GalacticState;

static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

static inline float sin_approx(float x)
{
    const float twoPi = 6.28318530718f;
    const float pi = 3.14159265359f;
    const float invTwoPi = 0.15915494309f;
    x = x - twoPi * (float)((int)(x * invTwoPi));
    if (x < 0.0f) x += twoPi;
    float sign = 1.0f;
    if (x > pi) {
        x -= pi;
        sign = -1.0f;
    }
    if (x > 1.57079632679f) x = pi - x;
    float x2 = x * x;
    float y = x;
    y -= x * x2 * 0.16666667f;
    x *= x2;
    y += x * x2 * 0.0083333310f;
    x *= x2;
    y -= x * x2 * 0.0001984090f;
    return y * sign;
}

static inline void gal_reset_header(GalacticState *st)
{
    st->magic = GALACTIC_MAGIC;
    st->version = GALACTIC_VERSION;
    st->initialized = 0u;
    st->clearIndex = 16u;
}

static inline void gal_finish_init(GalacticState *st)
{
    int i;
    st->iirAL = st->iirBL = st->iirAR = st->iirBR = 0.0f;
    st->feedbackAL = st->feedbackBL = st->feedbackCL = st->feedbackDL = 0.0f;
    st->feedbackAR = st->feedbackBR = st->feedbackCR = st->feedbackDR = 0.0f;
    for (i = 0; i < 7; i++) {
        st->lastRefL[i] = 0.0f;
        st->lastRefR[i] = 0.0f;
    }
    st->thunderL = 0.0f;
    st->thunderR = 0.0f;
    st->vibM = 3.0f;
    st->oldfpd = 429496.7295f;

    st->countA = st->countB = st->countC = st->countD = 1;
    st->countE = st->countF = st->countG = st->countH = 1;
    st->countI = st->countJ = st->countK = st->countL = 1;
    st->countM = 1;
    st->cycle = 0;

    st->fpdL = 0x1234567u;
    st->fpdR = 0x89ABCDFu;
    st->initialized = 1u;
}

static inline void gal_clear_chunk(GalacticState *st)
{
    uint32_t *w = (uint32_t *)(void *)st;
    uint32_t startWord = st->clearIndex >> 2;
    uint32_t endWord = startWord + (GALACTIC_CLEAR_STEP >> 2);
    uint32_t totalWords = (uint32_t)(sizeof(GalacticState) >> 2);
    uint32_t i;

    if (endWord > totalWords) endWord = totalWords;
    for (i = startWord; i < endWord; i++) {
        w[i] = 0u;
    }
    st->clearIndex = endWord << 2;
    if (endWord >= totalWords) {
        gal_finish_init(st);
    }
}

static inline void gal_process_sample(GalacticState *st, float *sampleL, float *sampleR,
                                      float regen, float attenuate, float lowpass,
                                      float drift, float wet,
                                      int delayI, int delayJ, int delayK, int delayL,
                                      int delayA, int delayB, int delayC, int delayD,
                                      int delayE, int delayF, int delayG, int delayH)
{
    float inputSampleL = *sampleL;
    float inputSampleR = *sampleR;
    float drySampleL = inputSampleL;
    float drySampleR = inputSampleR;

    if (inputSampleL > -1.18e-23f && inputSampleL < 1.18e-23f) inputSampleL = (float)st->fpdL * 1.18e-17f;
    if (inputSampleR > -1.18e-23f && inputSampleR < 1.18e-23f) inputSampleR = (float)st->fpdR * 1.18e-17f;

    st->vibM += st->oldfpd * drift;
    if (st->vibM > 6.28318530718f) {
        st->vibM = 0.0f;
        st->oldfpd = 0.4294967295f + ((float)st->fpdL * 0.0000000000618f);
    }

    st->aML[st->countM] = inputSampleL * attenuate;
    st->aMR[st->countM] = inputSampleR * attenuate;
    st->countM++;
    if (st->countM < 0 || st->countM > 256) st->countM = 0;

    {
        float offsetML = (sin_approx(st->vibM) + 1.0f) * 127.0f;
        float offsetMR = (sin_approx(st->vibM + 1.57079632679f) + 1.0f) * 127.0f;
        int offsetMLInt = (int)offsetML;
        int offsetMRInt = (int)offsetMR;
        float fracML = offsetML - (float)offsetMLInt;
        float fracMR = offsetMR - (float)offsetMRInt;
        int workingML = st->countM + offsetMLInt;
        int workingMR = st->countM + offsetMRInt;
        float interpolML = GAL_READ(st->aML, workingML, 256) * (1.0f - fracML);
        interpolML += GAL_READ(st->aML, workingML + 1, 256) * fracML;
        float interpolMR = GAL_READ(st->aMR, workingMR, 256) * (1.0f - fracMR);
        interpolMR += GAL_READ(st->aMR, workingMR + 1, 256) * fracMR;
        inputSampleL = interpolML;
        inputSampleR = interpolMR;
    }

    st->iirAL = (st->iirAL * (1.0f - lowpass)) + (inputSampleL * lowpass);
    st->iirAR = (st->iirAR * (1.0f - lowpass)) + (inputSampleR * lowpass);
    inputSampleL = st->iirAL;
    inputSampleR = st->iirAR;

    st->cycle++;
    if (st->cycle >= 1) {
        st->aIL[st->countI] = inputSampleL + (st->feedbackAR * regen);
        st->aJL[st->countJ] = inputSampleL + (st->feedbackBR * regen);
        st->aKL[st->countK] = inputSampleL + (st->feedbackCR * regen);
        st->aLL[st->countL] = inputSampleL + (st->feedbackDR * regen);
        st->aIR[st->countI] = inputSampleR + (st->feedbackAL * regen);
        st->aJR[st->countJ] = inputSampleR + (st->feedbackBL * regen);
        st->aKR[st->countK] = inputSampleR + (st->feedbackCL * regen);
        st->aLR[st->countL] = inputSampleR + (st->feedbackDL * regen);

        st->countI++; if (st->countI < 0 || st->countI > delayI) st->countI = 0;
        st->countJ++; if (st->countJ < 0 || st->countJ > delayJ) st->countJ = 0;
        st->countK++; if (st->countK < 0 || st->countK > delayK) st->countK = 0;
        st->countL++; if (st->countL < 0 || st->countL > delayL) st->countL = 0;

        float outIL = GAL_READ(st->aIL, st->countI, delayI);
        float outJL = GAL_READ(st->aJL, st->countJ, delayJ);
        float outKL = GAL_READ(st->aKL, st->countK, delayK);
        float outLL = GAL_READ(st->aLL, st->countL, delayL);
        float outIR = GAL_READ(st->aIR, st->countI, delayI);
        float outJR = GAL_READ(st->aJR, st->countJ, delayJ);
        float outKR = GAL_READ(st->aKR, st->countK, delayK);
        float outLR = GAL_READ(st->aLR, st->countL, delayL);

        st->aAL[st->countA] = outIL - (outJL + outKL + outLL);
        st->aBL[st->countB] = outJL - (outIL + outKL + outLL);
        st->aCL[st->countC] = outKL - (outIL + outJL + outLL);
        st->aDL[st->countD] = outLL - (outIL + outJL + outKL);
        st->aAR[st->countA] = outIR - (outJR + outKR + outLR);
        st->aBR[st->countB] = outJR - (outIR + outKR + outLR);
        st->aCR[st->countC] = outKR - (outIR + outJR + outLR);
        st->aDR[st->countD] = outLR - (outIR + outJR + outKR);

        st->countA++; if (st->countA < 0 || st->countA > delayA) st->countA = 0;
        st->countB++; if (st->countB < 0 || st->countB > delayB) st->countB = 0;
        st->countC++; if (st->countC < 0 || st->countC > delayC) st->countC = 0;
        st->countD++; if (st->countD < 0 || st->countD > delayD) st->countD = 0;

        float outAL = GAL_READ(st->aAL, st->countA, delayA);
        float outBL = GAL_READ(st->aBL, st->countB, delayB);
        float outCL = GAL_READ(st->aCL, st->countC, delayC);
        float outDL = GAL_READ(st->aDL, st->countD, delayD);
        float outAR = GAL_READ(st->aAR, st->countA, delayA);
        float outBR = GAL_READ(st->aBR, st->countB, delayB);
        float outCR = GAL_READ(st->aCR, st->countC, delayC);
        float outDR = GAL_READ(st->aDR, st->countD, delayD);

        st->aEL[st->countE] = outAL - (outBL + outCL + outDL);
        st->aFL[st->countF] = outBL - (outAL + outCL + outDL);
        st->aGL[st->countG] = outCL - (outAL + outBL + outDL);
        st->aHL[st->countH] = outDL - (outAL + outBL + outCL);
        st->aER[st->countE] = outAR - (outBR + outCR + outDR);
        st->aFR[st->countF] = outBR - (outAR + outCR + outDR);
        st->aGR[st->countG] = outCR - (outAR + outBR + outDR);
        st->aHR[st->countH] = outDR - (outAR + outBR + outCR);

        st->countE++; if (st->countE < 0 || st->countE > delayE) st->countE = 0;
        st->countF++; if (st->countF < 0 || st->countF > delayF) st->countF = 0;
        st->countG++; if (st->countG < 0 || st->countG > delayG) st->countG = 0;
        st->countH++; if (st->countH < 0 || st->countH > delayH) st->countH = 0;

        float outEL = GAL_READ(st->aEL, st->countE, delayE);
        float outFL = GAL_READ(st->aFL, st->countF, delayF);
        float outGL = GAL_READ(st->aGL, st->countG, delayG);
        float outHL = GAL_READ(st->aHL, st->countH, delayH);
        float outER = GAL_READ(st->aER, st->countE, delayE);
        float outFR = GAL_READ(st->aFR, st->countF, delayF);
        float outGR = GAL_READ(st->aGR, st->countG, delayG);
        float outHR = GAL_READ(st->aHR, st->countH, delayH);

        st->feedbackAL = outEL - (outFL + outGL + outHL);
        st->feedbackBL = outFL - (outEL + outGL + outHL);
        st->feedbackCL = outGL - (outEL + outFL + outHL);
        st->feedbackDL = outHL - (outEL + outFL + outGL);
        st->feedbackAR = outER - (outFR + outGR + outHR);
        st->feedbackBR = outFR - (outER + outGR + outHR);
        st->feedbackCR = outGR - (outER + outFR + outHR);
        st->feedbackDR = outHR - (outER + outFR + outGR);

        inputSampleL = (outEL + outFL + outGL + outHL) * 0.125f;
        inputSampleR = (outER + outFR + outGR + outHR) * 0.125f;
        st->lastRefL[0] = inputSampleL;
        st->lastRefR[0] = inputSampleR;
        st->cycle = 0;
    } else {
        inputSampleL = st->lastRefL[st->cycle];
        inputSampleR = st->lastRefR[st->cycle];
    }

    st->iirBL = (st->iirBL * (1.0f - lowpass)) + (inputSampleL * lowpass);
    st->iirBR = (st->iirBR * (1.0f - lowpass)) + (inputSampleR * lowpass);
    /* Makeup gain: the raw tank output sits well below the dry level on the
     * pedal (hardware feedback "ok but quiet"), so lift the wet path. */
    inputSampleL = st->iirBL * 1.8f;
    inputSampleR = st->iirBR * 1.8f;

    if (wet < 1.0f) {
        inputSampleL = (inputSampleL * wet) + (drySampleL * (1.0f - wet));
        inputSampleR = (inputSampleR * wet) + (drySampleR * (1.0f - wet));
    }

    st->fpdL ^= st->fpdL << 13;
    st->fpdL ^= st->fpdL >> 17;
    st->fpdL ^= st->fpdL << 5;
    st->fpdR ^= st->fpdR << 13;
    st->fpdR ^= st->fpdR >> 17;
    st->fpdR ^= st->fpdR << 5;

    *sampleL = inputSampleL;
    *sampleR = inputSampleR;
}

void GALACTIC_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;

    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end = (uintptr_t)desc[1];
    unsigned int span = desc[2];
    uintptr_t stateBase = align4(base);
    uintptr_t requiredEnd = stateBase + sizeof(GalacticState);
    uintptr_t bytes = end - base;

    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    if (bytes < sizeof(GalacticState) || span < bytes) return;
    if (requiredEnd > end) return;

    GalacticState *st = (GalacticState *)stateBase;
    if (st->magic != GALACTIC_MAGIC || st->version != GALACTIC_VERSION) {
        gal_reset_header(st);
        return;
    }
    if (!st->initialized) {
        gal_clear_chunk(st);
        return;
    }

    float A = GAL_PARAM_NORM(params[GALACTIC_REPLACE_SLOT], GALACTIC_REPLACE_DEFAULT_NORM);
    float B = GAL_PARAM_NORM(params[GALACTIC_BRIGHT_SLOT], GALACTIC_BRIGHT_DEFAULT_NORM);
    float C = GAL_PARAM_NORM(params[GALACTIC_DETUNE_SLOT], GALACTIC_DETUNE_DEFAULT_NORM);
    float D = GAL_PARAM_NORM(params[GALACTIC_BIGNESS_SLOT], GALACTIC_BIGNESS_DEFAULT_NORM);
    float E = GAL_PARAM_NORM(params[GALACTIC_MIX_SLOT], GALACTIC_MIX_DEFAULT_NORM);

    float regen = 0.125f - (A * 0.0625f);
    float attenuate = A * 0.6665f;
    float lowpass = B + 0.00001f;
    lowpass *= lowpass;
    float drift = C * C * C * 0.001f;
    float size = (D * 1.77f) + 0.1f;
    float wetInv = 1.0f - E;
    float wet = 1.0f - (wetInv * wetInv * wetInv);

    int delayI = (int)(3407.0f * size);
    int delayJ = (int)(1823.0f * size);
    int delayK = (int)(859.0f * size);
    int delayL = (int)(331.0f * size);
    int delayA = (int)(4801.0f * size);
    int delayB = (int)(2909.0f * size);
    int delayC = (int)(1153.0f * size);
    int delayD = (int)(461.0f * size);
    int delayE = (int)(7607.0f * size);
    int delayF = (int)(4217.0f * size);
    int delayG = (int)(2269.0f * size);
    int delayH = (int)(1597.0f * size);

    int i;
    for (i = 0; i < 8; i++) {
        float sL = fxBuf[i];
        float sR = fxBuf[i + 8];
        gal_process_sample(st, &sL, &sR, regen, attenuate, lowpass, drift, wet,
                           delayI, delayJ, delayK, delayL,
                           delayA, delayB, delayC, delayD,
                           delayE, delayF, delayG, delayH);
        fxBuf[i] = sL;
        fxBuf[i + 8] = sR;
    }
}
