/*
 * VerbTiny by Chris Johnson (airwindows) - MIT licence.
 * Zoom Multistomp port candidate.
 *
 * Source reference:
 *   airwindows-ref/plugins/WinVST/VerbTiny/VerbTinyProc.cpp
 *
 * The Airwindows delay network is held in the host-provided ctx[3] descriptor
 * arena rather than .fardata. The float32 dither tail is omitted, matching the
 * existing Zoom Airwindows ports.
 */

#include <stdint.h>

#include "../common/zoom_params.h"
#include "verbtiny_params.h"

#ifndef VERBTINY_AUDIO_FUNC
#define VERBTINY_AUDIO_FUNC Fx_REV_VerbTiny
#endif

#define VERBTINY_DO_PRAGMA(x) _Pragma(#x)
#define VERBTINY_EXPAND_PRAGMA(x) VERBTINY_DO_PRAGMA(x)
#define VERBTINY_CODE_SECTION(func) VERBTINY_EXPAND_PRAGMA(CODE_SECTION(func, ".audio"))
VERBTINY_CODE_SECTION(VERBTINY_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define VERBTINY_MAGIC 0x56544E59u
#define VERBTINY_VERSION 1u
#define VERBTINY_CLEAR_STEP 512u
#define VERBTINY_LINES 16
#define VERBTINY_MAX_DELAY 1406
#define VERBTINY_LINE_LEN (VERBTINY_MAX_DELAY + 5)

enum {
    VT_A = 0, VT_B, VT_C, VT_D,
    VT_E, VT_F, VT_G, VT_H,
    VT_I, VT_J, VT_K, VT_L,
    VT_M, VT_N, VT_O, VT_P
};

enum {
    VT_BEZ_AL,
    VT_BEZ_AR,
    VT_BEZ_BL,
    VT_BEZ_BR,
    VT_BEZ_CL,
    VT_BEZ_CR,
    VT_BEZ_SAMPL,
    VT_BEZ_SAMPR,
    VT_BEZ_CYCLE,
    VT_BEZ_TOTAL
};

#define VT_DELAY_A 136
#define VT_DELAY_B 52
#define VT_DELAY_C 53
#define VT_DELAY_D 1261
#define VT_DELAY_E 209
#define VT_DELAY_F 473
#define VT_DELAY_G 549
#define VT_DELAY_H 29
#define VT_DELAY_I 92
#define VT_DELAY_J 1137
#define VT_DELAY_K 1406
#define VT_DELAY_L 994
#define VT_DELAY_M 1314
#define VT_DELAY_N 191
#define VT_DELAY_O 1263
#define VT_DELAY_P 103

#define VT_HEAD 2
#define VT_OFF_A 0
#define VT_OFF_B (VT_OFF_A + VT_DELAY_A + VT_HEAD)
#define VT_OFF_C (VT_OFF_B + VT_DELAY_B + VT_HEAD)
#define VT_OFF_D (VT_OFF_C + VT_DELAY_C + VT_HEAD)
#define VT_OFF_E (VT_OFF_D + VT_DELAY_D + VT_HEAD)
#define VT_OFF_F (VT_OFF_E + VT_DELAY_E + VT_HEAD)
#define VT_OFF_G (VT_OFF_F + VT_DELAY_F + VT_HEAD)
#define VT_OFF_H (VT_OFF_G + VT_DELAY_G + VT_HEAD)
#define VT_OFF_I (VT_OFF_H + VT_DELAY_H + VT_HEAD)
#define VT_OFF_J (VT_OFF_I + VT_DELAY_I + VT_HEAD)
#define VT_OFF_K (VT_OFF_J + VT_DELAY_J + VT_HEAD)
#define VT_OFF_L (VT_OFF_K + VT_DELAY_K + VT_HEAD)
#define VT_OFF_M (VT_OFF_L + VT_DELAY_L + VT_HEAD)
#define VT_OFF_N (VT_OFF_M + VT_DELAY_M + VT_HEAD)
#define VT_OFF_O (VT_OFF_N + VT_DELAY_N + VT_HEAD)
#define VT_OFF_P (VT_OFF_O + VT_DELAY_O + VT_HEAD)
#define VT_LINESUM (VT_OFF_P + VT_DELAY_P + VT_HEAD)

/* Per-line delay segments packed into one flat array (each line uses only
 * 0..VT_DELAY_x). Was [16][MAX_DELAY+5] for every line ~353 KB; now ~145 KB,
 * identical math. LN() resolves a line's base inside the flat buffer. */
#define LN(arr, X) (st->arr + VT_OFF_##X)

typedef struct VerbTinyState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t clearIndex;

    float aL[VT_LINESUM];
    float aR[VT_LINESUM];
    float bL[VT_LINESUM];
    float bR[VT_LINESUM];

    int cL[VERBTINY_LINES];
    int cR[VERBTINY_LINES];

    float fL[4];
    float fR[4];
    float gL[4];
    float gR[4];

    float bez[VT_BEZ_TOTAL];
    float bezF[VT_BEZ_TOTAL];
    uint32_t fpdL;
    uint32_t fpdR;
} VerbTinyState;


static inline uintptr_t align4(uintptr_t x)
{
    return (x + 3u) & ~(uintptr_t)3u;
}

static inline float recip_approx_pos(float x)
{
    union { float f; uint32_t u; } conv;
    conv.f = x;
    conv.u = 0x7EF311C3u - conv.u;
    float y = conv.f;
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    y = y * (2.0f - x * y);
    return y;
}

static inline float clampf_local(float x, float lo, float hi)
{
    if (x < lo) return lo;
    if (x > hi) return hi;
    return x;
}

static inline float vt_param_norm(float raw, float fallback_norm, int group_empty)
{
    if (raw != raw) return zoom_clamp01(fallback_norm);
    if (raw < 0.0f) return zoom_clamp01(fallback_norm);
    if (raw <= 0.0001f) return group_empty ? zoom_clamp01(fallback_norm) : 0.0f;
    if (raw <= 1.0f) return zoom_clamp01(raw);
    if (raw <= 100.0f) return zoom_clamp01(raw * 0.01f);
    return zoom_clamp01(fallback_norm);
}

static inline float vt_tap(float *line, int count, int delay)
{
    int idx = count - ((count > delay) ? delay + 1 : 0);
    return line[idx];
}

static inline void vt_inc(int *counter, int delay)
{
    *counter += 1;
    if (*counter < 0 || *counter > delay) *counter = 0;
}

static inline void vt_householder_write(
    float *dst0,
    float *dst1,
    float *dst2,
    float *dst3,
    int c0, int c1, int c2, int c3,
    float hA, float hB, float hC, float hD)
{
    dst0[c0] = hA - (hB + hC + hD);
    dst1[c1] = hB - (hA + hC + hD);
    dst2[c2] = hC - (hA + hB + hD);
    dst3[c3] = hD - (hA + hB + hC);
}

static inline void vt_reset_header(VerbTinyState *st)
{
    st->magic = VERBTINY_MAGIC;
    st->version = VERBTINY_VERSION;
    st->initialized = 0u;
    st->clearIndex = 16u;
}

static inline void vt_finish_init(VerbTinyState *st)
{
    int i;
    for (i = 0; i < VERBTINY_LINES; i++) {
        st->cL[i] = 1;
        st->cR[i] = 1;
    }
    for (i = 0; i < 4; i++) {
        st->fL[i] = 0.0f;
        st->fR[i] = 0.0f;
        st->gL[i] = 0.0f;
        st->gR[i] = 0.0f;
    }
    for (i = 0; i < VT_BEZ_TOTAL; i++) {
        st->bez[i] = 0.0f;
        st->bezF[i] = 0.0f;
    }
    st->bez[VT_BEZ_CYCLE] = 1.0f;
    st->bezF[VT_BEZ_CYCLE] = 1.0f;
    st->fpdL = 0x1234567u;
    st->fpdR = 0x89ABCDFu;
    st->initialized = 1u;
}

static inline void vt_clear_chunk(VerbTinyState *st)
{
    uint32_t *w = (uint32_t *)(void *)st;
    uint32_t startWord = st->clearIndex >> 2;
    uint32_t endWord = startWord + (VERBTINY_CLEAR_STEP >> 2);
    uint32_t totalWords = (uint32_t)(sizeof(VerbTinyState) >> 2);
    uint32_t i;

    if (endWord > totalWords) endWord = totalWords;
    for (i = startWord; i < endWord; i++) {
        w[i] = 0u;
    }
    st->clearIndex = endWord << 2;
    if (endWord >= totalWords) {
        vt_finish_init(st);
    }
}

static inline void vt_process_sample(VerbTinyState *st, float *sampleL, float *sampleR,
                                     float reg4n, float attenuate, float derez,
                                     float bezTrim, float derezFreq,
                                     float bezFreqTrim, float wider, float wet)
{
    float inputSampleL = *sampleL;
    float inputSampleR = *sampleR;
    if (inputSampleL > -1.18e-23f && inputSampleL < 1.18e-23f) inputSampleL = (float)st->fpdL * 1.18e-17f;
    if (inputSampleR > -1.18e-23f && inputSampleR < 1.18e-23f) inputSampleR = (float)st->fpdR * 1.18e-17f;
    float drySampleL = inputSampleL;
    float drySampleR = inputSampleR;

    st->bez[VT_BEZ_CYCLE] += derez;
    st->bez[VT_BEZ_SAMPL] += inputSampleL * attenuate * derez;
    st->bez[VT_BEZ_SAMPR] += inputSampleR * attenuate * derez;

    if (st->bez[VT_BEZ_CYCLE] > 1.0f) {
        float mainSampleL = st->bez[VT_BEZ_SAMPL];
        float dualmonoSampleL = st->bez[VT_BEZ_SAMPR];
        float mainSampleR;
        float dualmonoSampleR;
        float hA, hB, hC, hD;

        st->bez[VT_BEZ_CYCLE] = 0.0f;

        LN(aL,A)[st->cL[VT_A]] = mainSampleL + (st->fR[0] * reg4n);
        LN(aL,B)[st->cL[VT_B]] = mainSampleL + (st->fR[1] * reg4n);
        LN(aL,C)[st->cL[VT_C]] = mainSampleL + (st->fR[2] * reg4n);
        LN(aL,D)[st->cL[VT_D]] = mainSampleL + (st->fR[3] * reg4n);
        LN(bL,A)[st->cL[VT_A]] = dualmonoSampleL + (st->gL[0] * reg4n);
        LN(bL,B)[st->cL[VT_B]] = dualmonoSampleL + (st->gL[1] * reg4n);
        LN(bL,C)[st->cL[VT_C]] = dualmonoSampleL + (st->gL[2] * reg4n);
        LN(bL,D)[st->cL[VT_D]] = dualmonoSampleL + (st->gL[3] * reg4n);

        vt_inc(&st->cL[VT_A], VT_DELAY_A);
        vt_inc(&st->cL[VT_B], VT_DELAY_B);
        vt_inc(&st->cL[VT_C], VT_DELAY_C);
        vt_inc(&st->cL[VT_D], VT_DELAY_D);

        hA = vt_tap(LN(aL,A), st->cL[VT_A], VT_DELAY_A);
        hB = vt_tap(LN(aL,B), st->cL[VT_B], VT_DELAY_B);
        hC = vt_tap(LN(aL,C), st->cL[VT_C], VT_DELAY_C);
        hD = vt_tap(LN(aL,D), st->cL[VT_D], VT_DELAY_D);
        vt_householder_write(LN(aL,E), LN(aL,F), LN(aL,G), LN(aL,H),
                             st->cL[VT_E], st->cL[VT_F], st->cL[VT_G], st->cL[VT_H],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bL,A), st->cL[VT_A], VT_DELAY_A);
        hB = vt_tap(LN(bL,B), st->cL[VT_B], VT_DELAY_B);
        hC = vt_tap(LN(bL,C), st->cL[VT_C], VT_DELAY_C);
        hD = vt_tap(LN(bL,D), st->cL[VT_D], VT_DELAY_D);
        vt_householder_write(LN(bL,E), LN(bL,F), LN(bL,G), LN(bL,H),
                             st->cL[VT_E], st->cL[VT_F], st->cL[VT_G], st->cL[VT_H],
                             hA, hB, hC, hD);

        vt_inc(&st->cL[VT_E], VT_DELAY_E);
        vt_inc(&st->cL[VT_F], VT_DELAY_F);
        vt_inc(&st->cL[VT_G], VT_DELAY_G);
        vt_inc(&st->cL[VT_H], VT_DELAY_H);

        hA = vt_tap(LN(aL,E), st->cL[VT_E], VT_DELAY_E);
        hB = vt_tap(LN(aL,F), st->cL[VT_F], VT_DELAY_F);
        hC = vt_tap(LN(aL,G), st->cL[VT_G], VT_DELAY_G);
        hD = vt_tap(LN(aL,H), st->cL[VT_H], VT_DELAY_H);
        vt_householder_write(LN(aL,I), LN(aL,J), LN(aL,K), LN(aL,L),
                             st->cL[VT_I], st->cL[VT_J], st->cL[VT_K], st->cL[VT_L],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bL,E), st->cL[VT_E], VT_DELAY_E);
        hB = vt_tap(LN(bL,F), st->cL[VT_F], VT_DELAY_F);
        hC = vt_tap(LN(bL,G), st->cL[VT_G], VT_DELAY_G);
        hD = vt_tap(LN(bL,H), st->cL[VT_H], VT_DELAY_H);
        vt_householder_write(LN(bL,I), LN(bL,J), LN(bL,K), LN(bL,L),
                             st->cL[VT_I], st->cL[VT_J], st->cL[VT_K], st->cL[VT_L],
                             hA, hB, hC, hD);

        vt_inc(&st->cL[VT_I], VT_DELAY_I);
        vt_inc(&st->cL[VT_J], VT_DELAY_J);
        vt_inc(&st->cL[VT_K], VT_DELAY_K);
        vt_inc(&st->cL[VT_L], VT_DELAY_L);

        hA = vt_tap(LN(aL,I), st->cL[VT_I], VT_DELAY_I);
        hB = vt_tap(LN(aL,J), st->cL[VT_J], VT_DELAY_J);
        hC = vt_tap(LN(aL,K), st->cL[VT_K], VT_DELAY_K);
        hD = vt_tap(LN(aL,L), st->cL[VT_L], VT_DELAY_L);
        vt_householder_write(LN(aL,M), LN(aL,N), LN(aL,O), LN(aL,P),
                             st->cL[VT_M], st->cL[VT_N], st->cL[VT_O], st->cL[VT_P],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bL,I), st->cL[VT_I], VT_DELAY_I);
        hB = vt_tap(LN(bL,J), st->cL[VT_J], VT_DELAY_J);
        hC = vt_tap(LN(bL,K), st->cL[VT_K], VT_DELAY_K);
        hD = vt_tap(LN(bL,L), st->cL[VT_L], VT_DELAY_L);
        vt_householder_write(LN(bL,M), LN(bL,N), LN(bL,O), LN(bL,P),
                             st->cL[VT_M], st->cL[VT_N], st->cL[VT_O], st->cL[VT_P],
                             hA, hB, hC, hD);

        vt_inc(&st->cL[VT_M], VT_DELAY_M);
        vt_inc(&st->cL[VT_N], VT_DELAY_N);
        vt_inc(&st->cL[VT_O], VT_DELAY_O);
        vt_inc(&st->cL[VT_P], VT_DELAY_P);

        hA = vt_tap(LN(aL,M), st->cL[VT_M], VT_DELAY_M);
        hB = vt_tap(LN(aL,N), st->cL[VT_N], VT_DELAY_N);
        hC = vt_tap(LN(aL,O), st->cL[VT_O], VT_DELAY_O);
        hD = vt_tap(LN(aL,P), st->cL[VT_P], VT_DELAY_P);
        st->fL[0] = hA - (hB + hC + hD);
        st->fL[1] = hB - (hA + hC + hD);
        st->fL[2] = hC - (hA + hB + hD);
        st->fL[3] = hD - (hA + hB + hC);
        mainSampleL = (hA + hB + hC + hD) * 0.125f;

        hA = vt_tap(LN(bL,M), st->cL[VT_M], VT_DELAY_M);
        hB = vt_tap(LN(bL,N), st->cL[VT_N], VT_DELAY_N);
        hC = vt_tap(LN(bL,O), st->cL[VT_O], VT_DELAY_O);
        hD = vt_tap(LN(bL,P), st->cL[VT_P], VT_DELAY_P);
        st->gL[0] = hA - (hB + hC + hD);
        st->gL[1] = hB - (hA + hC + hD);
        st->gL[2] = hC - (hA + hB + hD);
        st->gL[3] = hD - (hA + hB + hC);
        dualmonoSampleL = (hA + hB + hC + hD) * 0.125f;

        mainSampleR = st->bez[VT_BEZ_SAMPR];
        dualmonoSampleR = st->bez[VT_BEZ_SAMPL];

        LN(aR,D)[st->cR[VT_D]] = mainSampleR + (st->fL[0] * reg4n);
        LN(aR,H)[st->cR[VT_H]] = mainSampleR + (st->fL[1] * reg4n);
        LN(aR,L)[st->cR[VT_L]] = mainSampleR + (st->fL[2] * reg4n);
        LN(aR,P)[st->cR[VT_P]] = mainSampleR + (st->fL[3] * reg4n);
        LN(bR,D)[st->cR[VT_D]] = dualmonoSampleR + (st->gR[0] * reg4n);
        LN(bR,H)[st->cR[VT_H]] = dualmonoSampleR + (st->gR[1] * reg4n);
        LN(bR,L)[st->cR[VT_L]] = dualmonoSampleR + (st->gR[2] * reg4n);
        LN(bR,P)[st->cR[VT_P]] = dualmonoSampleR + (st->gR[3] * reg4n);

        vt_inc(&st->cR[VT_D], VT_DELAY_D);
        vt_inc(&st->cR[VT_H], VT_DELAY_H);
        vt_inc(&st->cR[VT_L], VT_DELAY_L);
        vt_inc(&st->cR[VT_P], VT_DELAY_P);

        hA = vt_tap(LN(aR,D), st->cR[VT_D], VT_DELAY_D);
        hB = vt_tap(LN(aR,H), st->cR[VT_H], VT_DELAY_H);
        hC = vt_tap(LN(aR,L), st->cR[VT_L], VT_DELAY_L);
        hD = vt_tap(LN(aR,P), st->cR[VT_P], VT_DELAY_P);
        vt_householder_write(LN(aR,C), LN(aR,G), LN(aR,K), LN(aR,O),
                             st->cR[VT_C], st->cR[VT_G], st->cR[VT_K], st->cR[VT_O],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bR,D), st->cR[VT_D], VT_DELAY_D);
        hB = vt_tap(LN(bR,H), st->cR[VT_H], VT_DELAY_H);
        hC = vt_tap(LN(bR,L), st->cR[VT_L], VT_DELAY_L);
        hD = vt_tap(LN(bR,P), st->cR[VT_P], VT_DELAY_P);
        vt_householder_write(LN(bR,C), LN(bR,G), LN(bR,K), LN(bR,O),
                             st->cR[VT_C], st->cR[VT_G], st->cR[VT_K], st->cR[VT_O],
                             hA, hB, hC, hD);

        vt_inc(&st->cR[VT_C], VT_DELAY_C);
        vt_inc(&st->cR[VT_G], VT_DELAY_G);
        vt_inc(&st->cR[VT_K], VT_DELAY_K);
        vt_inc(&st->cR[VT_O], VT_DELAY_O);

        hA = vt_tap(LN(aR,C), st->cR[VT_C], VT_DELAY_C);
        hB = vt_tap(LN(aR,G), st->cR[VT_G], VT_DELAY_G);
        hC = vt_tap(LN(aR,K), st->cR[VT_K], VT_DELAY_K);
        hD = vt_tap(LN(aR,O), st->cR[VT_O], VT_DELAY_O);
        vt_householder_write(LN(aR,B), LN(aR,F), LN(aR,J), LN(aR,N),
                             st->cR[VT_B], st->cR[VT_F], st->cR[VT_J], st->cR[VT_N],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bR,C), st->cR[VT_C], VT_DELAY_C);
        hB = vt_tap(LN(bR,G), st->cR[VT_G], VT_DELAY_G);
        hC = vt_tap(LN(bR,K), st->cR[VT_K], VT_DELAY_K);
        hD = vt_tap(LN(bR,O), st->cR[VT_O], VT_DELAY_O);
        vt_householder_write(LN(bR,B), LN(bR,F), LN(bR,J), LN(bR,N),
                             st->cR[VT_B], st->cR[VT_F], st->cR[VT_J], st->cR[VT_N],
                             hA, hB, hC, hD);

        vt_inc(&st->cR[VT_B], VT_DELAY_B);
        vt_inc(&st->cR[VT_F], VT_DELAY_F);
        vt_inc(&st->cR[VT_J], VT_DELAY_J);
        vt_inc(&st->cR[VT_N], VT_DELAY_N);

        hA = vt_tap(LN(aR,B), st->cR[VT_B], VT_DELAY_B);
        hB = vt_tap(LN(aR,F), st->cR[VT_F], VT_DELAY_F);
        hC = vt_tap(LN(aR,J), st->cR[VT_J], VT_DELAY_J);
        hD = vt_tap(LN(aR,N), st->cR[VT_N], VT_DELAY_N);
        vt_householder_write(LN(aR,A), LN(aR,E), LN(aR,I), LN(aR,M),
                             st->cR[VT_A], st->cR[VT_E], st->cR[VT_I], st->cR[VT_M],
                             hA, hB, hC, hD);
        hA = vt_tap(LN(bR,B), st->cR[VT_B], VT_DELAY_B);
        hB = vt_tap(LN(bR,F), st->cR[VT_F], VT_DELAY_F);
        hC = vt_tap(LN(bR,J), st->cR[VT_J], VT_DELAY_J);
        hD = vt_tap(LN(bR,N), st->cR[VT_N], VT_DELAY_N);
        vt_householder_write(LN(bR,A), LN(bR,E), LN(bR,I), LN(bR,M),
                             st->cR[VT_A], st->cR[VT_E], st->cR[VT_I], st->cR[VT_M],
                             hA, hB, hC, hD);

        vt_inc(&st->cR[VT_A], VT_DELAY_A);
        vt_inc(&st->cR[VT_E], VT_DELAY_E);
        vt_inc(&st->cR[VT_I], VT_DELAY_I);
        vt_inc(&st->cR[VT_M], VT_DELAY_M);

        hA = vt_tap(LN(aR,A), st->cR[VT_A], VT_DELAY_A);
        hB = vt_tap(LN(aR,E), st->cR[VT_E], VT_DELAY_E);
        hC = vt_tap(LN(aR,I), st->cR[VT_I], VT_DELAY_I);
        hD = vt_tap(LN(aR,M), st->cR[VT_M], VT_DELAY_M);
        st->fR[0] = hA - (hB + hC + hD);
        st->fR[1] = hB - (hA + hC + hD);
        st->fR[2] = hC - (hA + hB + hD);
        st->fR[3] = hD - (hA + hB + hC);
        mainSampleR = (hA + hB + hC + hD) * 0.125f;

        hA = vt_tap(LN(bR,A), st->cR[VT_A], VT_DELAY_A);
        hB = vt_tap(LN(bR,E), st->cR[VT_E], VT_DELAY_E);
        hC = vt_tap(LN(bR,I), st->cR[VT_I], VT_DELAY_I);
        hD = vt_tap(LN(bR,M), st->cR[VT_M], VT_DELAY_M);
        st->gR[0] = hA - (hB + hC + hD);
        st->gR[1] = hB - (hA + hC + hD);
        st->gR[2] = hC - (hA + hB + hD);
        st->gR[3] = hD - (hA + hB + hC);
        dualmonoSampleR = (hA + hB + hC + hD) * 0.125f;

        if (wider < 1.0f) {
            inputSampleL = (dualmonoSampleR * wider) + (mainSampleL * (1.0f - wider));
            inputSampleR = (dualmonoSampleL * wider) + (mainSampleR * (1.0f - wider));
        } else {
            inputSampleL = (dualmonoSampleR * (2.0f - wider)) + (mainSampleL * (wider - 1.0f));
            inputSampleR = (dualmonoSampleL * (2.0f - wider)) + (-mainSampleR * (wider - 1.0f));
        }

        st->bez[VT_BEZ_CL] = st->bez[VT_BEZ_BL];
        st->bez[VT_BEZ_BL] = st->bez[VT_BEZ_AL];
        st->bez[VT_BEZ_AL] = inputSampleL;
        st->bez[VT_BEZ_SAMPL] = 0.0f;

        st->bez[VT_BEZ_CR] = st->bez[VT_BEZ_BR];
        st->bez[VT_BEZ_BR] = st->bez[VT_BEZ_AR];
        st->bez[VT_BEZ_AR] = inputSampleR;
        st->bez[VT_BEZ_SAMPR] = 0.0f;
    }

    {
        float X = st->bez[VT_BEZ_CYCLE] * bezTrim;
        float CBL = (st->bez[VT_BEZ_CL] * (1.0f - X)) + (st->bez[VT_BEZ_BL] * X);
        float CBR = (st->bez[VT_BEZ_CR] * (1.0f - X)) + (st->bez[VT_BEZ_BR] * X);
        float BAL = (st->bez[VT_BEZ_BL] * (1.0f - X)) + (st->bez[VT_BEZ_AL] * X);
        float BAR = (st->bez[VT_BEZ_BR] * (1.0f - X)) + (st->bez[VT_BEZ_AR] * X);
        inputSampleL = (st->bez[VT_BEZ_BL] + (CBL * (1.0f - X)) + (BAL * X)) * -0.25f;
        inputSampleR = (st->bez[VT_BEZ_BR] + (CBR * (1.0f - X)) + (BAR * X)) * -0.25f;

        st->bezF[VT_BEZ_CYCLE] += derezFreq;
        st->bezF[VT_BEZ_SAMPL] += inputSampleL * derezFreq;
        st->bezF[VT_BEZ_SAMPR] += inputSampleR * derezFreq;
        if (st->bezF[VT_BEZ_CYCLE] > 1.0f) {
            st->bezF[VT_BEZ_CYCLE] = 0.0f;
            st->bezF[VT_BEZ_CL] = st->bezF[VT_BEZ_BL];
            st->bezF[VT_BEZ_BL] = st->bezF[VT_BEZ_AL];
            st->bezF[VT_BEZ_AL] = st->bezF[VT_BEZ_SAMPL];
            st->bezF[VT_BEZ_SAMPL] = 0.0f;
            st->bezF[VT_BEZ_CR] = st->bezF[VT_BEZ_BR];
            st->bezF[VT_BEZ_BR] = st->bezF[VT_BEZ_AR];
            st->bezF[VT_BEZ_AR] = st->bezF[VT_BEZ_SAMPR];
            st->bezF[VT_BEZ_SAMPR] = 0.0f;
        }
        X = st->bezF[VT_BEZ_CYCLE] * bezFreqTrim;
        {
            float CBLfreq = (st->bezF[VT_BEZ_CL] * (1.0f - X)) + (st->bezF[VT_BEZ_BL] * X);
            float BALfreq = (st->bezF[VT_BEZ_BL] * (1.0f - X)) + (st->bezF[VT_BEZ_AL] * X);
            float CBRfreq = (st->bezF[VT_BEZ_CR] * (1.0f - X)) + (st->bezF[VT_BEZ_BR] * X);
            float BARfreq = (st->bezF[VT_BEZ_BR] * (1.0f - X)) + (st->bezF[VT_BEZ_AR] * X);
            inputSampleL = (st->bezF[VT_BEZ_BL] + (CBLfreq * (1.0f - X)) + (BALfreq * X)) * 0.5f;
            inputSampleR = (st->bezF[VT_BEZ_BR] + (CBRfreq * (1.0f - X)) + (BARfreq * X)) * 0.5f;
        }
    }

    *sampleL = (inputSampleL * wet) + (drySampleL * (1.0f - wet));
    *sampleR = (inputSampleR * wet) + (drySampleR * (1.0f - wet));
}

void VERBTINY_AUDIO_FUNC(unsigned int *ctx)
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
    uintptr_t requiredEnd = stateBase + sizeof(VerbTinyState);
    uintptr_t bytes = end - base;

    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    if (bytes < sizeof(VerbTinyState) || span < bytes) return;
    if (requiredEnd > end) return;

    VerbTinyState *st = (VerbTinyState *)stateBase;
    if (st->magic != VERBTINY_MAGIC || st->version != VERBTINY_VERSION) {
        vt_reset_header(st);
        return;
    }
    if (!st->initialized) {
        vt_clear_chunk(st);
        return;
    }

    float rawA = params[VERBTINY_REPLACE_SLOT];
    float rawB = params[VERBTINY_DEREZ_SLOT];
    float rawC = params[VERBTINY_FILTER_SLOT];
    float rawD = params[VERBTINY_WIDER_SLOT];
    float rawE = params[VERBTINY_DRYWET_SLOT];
    int groupEmpty = (rawA <= 0.0001f) && (rawB <= 0.0001f) && (rawC <= 0.0001f)
                  && (rawD <= 0.0001f) && (rawE <= 0.0001f);

    float A = vt_param_norm(rawA, VERBTINY_REPLACE_DEFAULT_NORM, groupEmpty);
    float B = vt_param_norm(rawB, VERBTINY_DEREZ_DEFAULT_NORM, groupEmpty);
    float C = vt_param_norm(rawC, VERBTINY_FILTER_DEFAULT_NORM, groupEmpty);
    float D = vt_param_norm(rawD, VERBTINY_WIDER_DEFAULT_NORM, groupEmpty);
    float E = vt_param_norm(rawE, VERBTINY_DRYWET_DEFAULT_NORM, groupEmpty);

    float oneMinusA = 1.0f - A;
    float shapedA = 1.0f - (oneMinusA * oneMinusA);
    float reg4n = 0.03125f + (shapedA * 0.03125f);
    float attenuate = shapedA;

    float derez = clampf_local(B * B, 0.0001f, 1.0f);
    int bezFraction = (int)recip_approx_pos(derez);
    if (bezFraction < 1) bezFraction = 1;
    float bezFracF = (float)bezFraction;
    float derezOut = recip_approx_pos(bezFracF);
    float bezTrim = 1.0f - (derezOut * (bezFracF * recip_approx_pos(bezFracF + 1.0f)));

    float derezFreq = clampf_local(C * C, 0.0001f, 1.0f);
    int bezFreqFraction = (int)recip_approx_pos(derezFreq);
    if (bezFreqFraction < 1) bezFreqFraction = 1;
    float bezFreqFracF = (float)bezFreqFraction;
    float derezFreqOut = recip_approx_pos(bezFreqFracF);
    float bezFreqTrim = 1.0f - (derezFreqOut * (bezFreqFracF * recip_approx_pos(bezFreqFracF + 1.0f)));

    float wider = D * 2.0f;
    float wet = E;

    int i;
    for (i = 0; i < 8; i++) {
        float sL = fxBuf[i];
        float sR = fxBuf[i + 8];
        vt_process_sample(st, &sL, &sR, reg4n, attenuate, derezOut, bezTrim,
                          derezFreqOut, bezFreqTrim, wider, wet);
        fxBuf[i] = sL;
        fxBuf[i + 8] = sR;
    }
}
