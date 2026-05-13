/*
 * StereoChorus by Chris Johnson (airwindows) - MIT licence.
 * Zoom Multistomp port attempt.
 *
 * This is the first ctx[3]-backed port attempt. It preserves the source
 * algorithm's large integer delay lines, Speed/Depth control laws, air
 * compensation, sweep phases, and interpolation core. The dither tail is not
 * reproduced yet because the Zoom path already stays float32 and the original
 * frexp/pow dither would pull in unproven runtime helpers.
 */

#include <stdint.h>

#include "../common/zoom_params.h"
#include "stereochorus_params.h"

#pragma CODE_SECTION(Fx_MOD_StChorus, ".audio")

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define STCHORUS_MAGIC 0x53434831u
#define STCHORUS_VERSION 1u
#define STCHORUS_DELAY_SAMPLES 65536u
#define STCHORUS_CLEAR_STEP 512u
typedef struct StChorusState {
    uint32_t magic;
    uint32_t version;
    uint32_t clearIndex;
    uint32_t initialized;

    float sweepL;
    float sweepR;
    int gcount;

    float airPrevL;
    float airEvenL;
    float airOddL;
    float airFactorL;
    float airPrevR;
    float airEvenR;
    float airOddR;
    float airFactorR;
    int flip;

    float lastRefL[7];
    float lastRefR[7];
    int cycle;

    uint32_t fpdL;
    uint32_t fpdR;
} StChorusState;

static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

static inline float absf_local(float x)
{
    return x < 0.0f ? -x : x;
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

    float pmx = pi - x;
    float xpmx = x * pmx;
    return sign * ((16.0f * xpmx) / (49.348022f - (4.0f * xpmx)));
}

static inline float pow10_source(float x)
{
    float x2 = x * x;
    float x4 = x2 * x2;
    float x8 = x4 * x4;
    return x8 * x2;
}

static inline void reset_state_header(StChorusState *st)
{
    int i;
    st->magic = STCHORUS_MAGIC;
    st->version = STCHORUS_VERSION;
    st->clearIndex = 0u;
    st->initialized = 0u;

    st->sweepL = 1.16355283466f; /* pi / 2.7 */
    st->sweepR = 3.14159265359f;
    st->gcount = 0;

    st->airPrevL = 0.0f;
    st->airEvenL = 0.0f;
    st->airOddL = 0.0f;
    st->airFactorL = 0.0f;
    st->airPrevR = 0.0f;
    st->airEvenR = 0.0f;
    st->airOddR = 0.0f;
    st->airFactorR = 0.0f;
    st->flip = 0;

    for (i = 0; i < 7; i++) {
        st->lastRefL[i] = 0.0f;
        st->lastRefR[i] = 0.0f;
    }
    st->cycle = 0;

    st->fpdL = 0x1234567u;
    st->fpdR = 0x89ABCDFu;
}

static inline void clear_delay_chunk(StChorusState *st, int *pL, int *pR)
{
    uint32_t end = st->clearIndex + STCHORUS_CLEAR_STEP;
    if (end > STCHORUS_DELAY_SAMPLES) end = STCHORUS_DELAY_SAMPLES;

    uint32_t i;
    for (i = st->clearIndex; i < end; i++) {
        pL[i] = 0;
        pR[i] = 0;
    }

    st->clearIndex = end;
    if (end >= STCHORUS_DELAY_SAMPLES) {
        st->initialized = 1u;
    }
}

void Fx_MOD_StChorus(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    unsigned int *desc = ZDL_PTR(unsigned int *, ctx[3]);
    if (!desc) return;

    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end = (uintptr_t)desc[1];
    if (end <= base) return;

    uintptr_t stateBase = align4(base);
    uintptr_t pLBase = align4(stateBase + sizeof(StChorusState));
    uintptr_t pRBase = pLBase + (STCHORUS_DELAY_SAMPLES * sizeof(int));
    uintptr_t requiredEnd = pRBase + (STCHORUS_DELAY_SAMPLES * sizeof(int));
    if (requiredEnd > end) return;

    StChorusState *st = (StChorusState *)stateBase;
    int *pL = (int *)pLBase;
    int *pR = (int *)pRBase;

    if (st->magic != STCHORUS_MAGIC || st->version != STCHORUS_VERSION) {
        reset_state_header(st);
    }
    if (!st->initialized) {
        clear_delay_chunk(st, pL, pR);
        return;
    }

    float A = zoom_param_norm(params[STCHORUS_SPEED_SLOT], STCHORUS_SPEED_DEFAULT_NORM);
    float B = zoom_param_norm(params[STCHORUS_DEPTH_SLOT], STCHORUS_DEPTH_DEFAULT_NORM);

    float speedBase = 0.32f + (A * 0.16666666667f);
    float speed = pow10_source(speedBase);
    float depth = (B * 0.01666666667f) / speed;
    const float twoPi = 6.28318530718f;

    int i;
    for (i = 0; i < 8; i++) {
        float inputSampleL = fxBuf[i];
        float inputSampleR = fxBuf[i + 8];

        if (absf_local(inputSampleL) < 1.18e-23f) {
            inputSampleL = (float)st->fpdL * 1.18e-17f;
        }
        if (absf_local(inputSampleR) < 1.18e-23f) {
            inputSampleR = (float)st->fpdR * 1.18e-17f;
        }

        st->cycle++;
        if (st->cycle >= 1) {
            st->airFactorL = st->airPrevL - inputSampleL;
            if (st->flip) {
                st->airEvenL += st->airFactorL;
                st->airOddL -= st->airFactorL;
                st->airFactorL = st->airEvenL;
            } else {
                st->airOddL += st->airFactorL;
                st->airEvenL -= st->airFactorL;
                st->airFactorL = st->airOddL;
            }
            st->airOddL = (st->airOddL - ((st->airOddL - st->airEvenL) * 0.00390625f)) * 0.99990001f;
            st->airEvenL = (st->airEvenL - ((st->airEvenL - st->airOddL) * 0.00390625f)) * 0.99990001f;
            st->airPrevL = inputSampleL;
            inputSampleL += st->airFactorL;

            st->airFactorR = st->airPrevR - inputSampleR;
            if (st->flip) {
                st->airEvenR += st->airFactorR;
                st->airOddR -= st->airFactorR;
                st->airFactorR = st->airEvenR;
            } else {
                st->airOddR += st->airFactorR;
                st->airEvenR -= st->airFactorR;
                st->airFactorR = st->airOddR;
            }
            st->airOddR = (st->airOddR - ((st->airOddR - st->airEvenR) * 0.00390625f)) * 0.99990001f;
            st->airEvenR = (st->airEvenR - ((st->airEvenR - st->airOddR) * 0.00390625f)) * 0.99990001f;
            st->airPrevR = inputSampleR;
            inputSampleR += st->airFactorR;

            st->flip = !st->flip;

            int tempL = 0;
            int tempR = 0;
            if (st->gcount < 1 || st->gcount > 32760) st->gcount = 32760;

            int count = st->gcount;
            pL[count + 32760] = pL[count] = (int)(inputSampleL * 8388352.0f);
            float offset = depth + (depth * sin_approx(st->sweepL));
            int whole = (int)offset;
            float frac = offset - (float)whole;
            count += whole;
            tempL += (int)((float)pL[count] * (1.0f - frac));
            tempL += pL[count + 1];
            tempL += (int)((float)pL[count + 2] * frac);
            tempL -= (int)((float)((pL[count] - pL[count + 1]) - (pL[count + 1] - pL[count + 2])) * 0.02f);

            count = st->gcount;
            pR[count + 32760] = pR[count] = (int)(inputSampleR * 8388352.0f);
            offset = depth + (depth * sin_approx(st->sweepR));
            whole = (int)offset;
            frac = offset - (float)whole;
            count += whole;
            tempR += (int)((float)pR[count] * (1.0f - frac));
            tempR += pR[count + 1];
            tempR += (int)((float)pR[count + 2] * frac);
            tempR -= (int)((float)((pR[count] - pR[count + 1]) - (pR[count + 1] - pR[count + 2])) * 0.02f);

            st->sweepL += speed;
            st->sweepR += speed;
            if (st->sweepL > twoPi) st->sweepL -= twoPi;
            if (st->sweepR > twoPi) st->sweepR -= twoPi;
            st->gcount--;

            inputSampleL = (float)tempL * 0.000000059606746f;
            inputSampleR = (float)tempR * 0.000000059606746f;

            st->lastRefL[0] = inputSampleL;
            st->lastRefR[0] = inputSampleR;
            st->cycle = 0;
            inputSampleL = st->lastRefL[0];
            inputSampleR = st->lastRefR[0];
        } else {
            inputSampleL = st->lastRefL[st->cycle];
            inputSampleR = st->lastRefR[st->cycle];
        }

        st->fpdL ^= st->fpdL << 13;
        st->fpdL ^= st->fpdL >> 17;
        st->fpdL ^= st->fpdL << 5;
        st->fpdR ^= st->fpdR << 13;
        st->fpdR ^= st->fpdR >> 17;
        st->fpdR ^= st->fpdR << 5;

        fxBuf[i] = inputSampleL;
        fxBuf[i + 8] = inputSampleR;
    }
}
