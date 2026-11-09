/* Spectrum: a live spectrum analyzer on the pedal screen (MS-70CDR 2.10).
 *
 * Audio passes through untouched. While its own card is on screen: capture
 * 1024 samples of (L+R)/2, Hann-windowed and stored straight into bit-reversed
 * order as the 512 complex points of a half-size FFT (even samples real, odd
 * imaginary); run the 9 radix-2 stages, 64 butterflies a callback; split
 * into the 512 bins of the real 1024-point spectrum; map the bins to 126
 * log-spaced columns (build.py's table) in dB with a tilt; then draw falling
 * bars with peak-hold dots over the background and hand the frame to zvis.
 * Every step is split so no callback does much. See ../common/zvis.h. */
#include <stdint.h>
#include "zvis.h"
#include "spectrum_art.h"

extern unsigned int _Fx_DLY_Spectrum_Info[];

#define MAGIC  0x53504543u                     /* 'SPEC' */
#define FXID   468u
#define HALF   512u                            /* complex FFT size */
#define BOT    (SPEC_PLOT_H - 2)               /* bars stand on row 58 */
#define BAR_H  (SPEC_PLOT_H - 3)               /* up to row 1 */
#define REF_DB 48.165f                         /* 10*log10(|X|^2) of a full-scale sine, Hann, N = 1024 */
#define HOLD   15u                             /* frames a peak dot stays before it falls */

enum { CAP, FFT, SPLIT, MAP, DRAW };

typedef struct {
    unsigned magic, phase, n, step;
    float range, irange, fall, tilt;
    float re[HALF], im[HALF], pw[HALF];
    float lvl[SPEC_COLS], pk[SPEC_COLS];
    unsigned char hold[SPEC_COLS];
    ZvState z;
} SpecState;

ZV_INLINE(f2u)
static inline uint32_t f2u(float f) { union { float f; uint32_t u; } v; v.f = f; return v.u; }
ZV_INLINE(u2f)
static inline float u2f(uint32_t u) { union { float f; uint32_t u; } v; v.u = u; return v.f; }

/* 10*log10(p) from the float's exponent and a quadratic for the mantissa (~0.05 dB). */
ZV_INLINE(db10)
static inline float db10(float p)
{
    uint32_t u = f2u(p);
    float e = (float)((int)((u >> 23) & 255u) - 127);
    float m = u2f((u & 0x7FFFFFu) | 0x3F800000u) - 1.0f;
    return 3.0103f * (e + m * (1.3465552f - 0.3465552f * m));
}

/* 1/x without the division helper: the C674x estimate and two Newton steps. */
ZV_INLINE(rcp)
static inline float rcp(float x)
{
#ifdef __TI_COMPILER_VERSION__
    float r = _rcpsp(x); r = r * (2.0f - x * r); return r * (2.0f - x * r);
#else
    return 1.0f / x;                           /* host test build */
#endif
}

ZV_INLINE(rev9)
static inline unsigned rev9(unsigned x)
{
    x = ((x & 0x5555u) << 1) | ((x >> 1) & 0x5555u);
    x = ((x & 0x3333u) << 2) | ((x >> 2) & 0x3333u);
    x = ((x & 0x0F0Fu) << 4) | ((x >> 4) & 0x0F0Fu);
    x = ((x & 0x00FFu) << 8) | ((x >> 8) & 0x00FFu);
    return (x >> 7) & 511u;
}

/* Rows y0..y1 of column x to black. */
ZV_INLINE(vspan)
static inline void vspan(ZvState *z, int x, int y0, int y1)
{
    int b;
    for (b = y0 >> 3; b <= y1 >> 3; ++b) {
        int lo = b == y0 >> 3 ? y0 & 7 : 0, hi = b == y1 >> 3 ? y1 & 7 : 7;
        z->frame[b * ZV_W + x] |= (unsigned char)((0xFFu << lo) & (0xFFu >> (7 - hi)));
    }
}

#pragma CODE_SECTION(Fx_DLY_Spectrum, ".audio")
void Fx_DLY_Spectrum(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    unsigned int *info = _Fx_DLY_Spectrum_Info;
    int on = params[0] >= 0.5f;                /* read first: not after zv_service's loops */
    uintptr_t base, end;
    SpecState *st;
    unsigned i;
    int visible;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(SpecState)) return;
    st = (SpecState *)base;
    if (st->magic != MAGIC) {
        st->magic = MAGIC; st->phase = CAP; st->n = 0; st->step = 0;
        for (i = 0; i < SPEC_COLS; ++i) { st->lvl[i] = 0.0f; st->pk[i] = 0.0f; st->hold[i] = 0; }
        zv_init(&st->z, FXID, info);
        return;
    }

    visible = zv_visible(&st->z, ctx);
    zv_service(&st->z, info, visible);
    /* Full screen: the firmware's knob boxes hidden, again every callback (they
     * can come back after our first callback; idempotent, see Skull). */
    zv_hide_knob_boxes(&st->z, info);
    if (!on || !visible) { st->phase = CAP; st->n = 0; return; }   /* off or not on screen: no work */

    if (st->phase == CAP) {                    /* 8 samples a callback, windowed, bit-reversed */
        for (i = 0; i < 8u; ++i) {
            unsigned m = st->n + i;
            float v = (fx[i] + fx[i + 8]) * 0.5f * (0.5f - 0.5f * SPEC_COS[m]);
            if (m & 1u) st->im[rev9(m >> 1)] = v; else st->re[rev9(m >> 1)] = v;
        }
        st->n += 8u;
        if (st->n >= SPEC_N) { st->n = 0; st->step = 0; st->phase = FFT; }
        return;
    }
    if (st->phase == FFT) {                    /* stage s = step/4 + 1, a quarter of its 256 butterflies */
        unsigned s = (st->step >> 2) + 1u, hm = 1u << (s - 1u), bf = (st->step & 3u) * 64u, e = bf + 64u;
        unsigned tstep = SPEC_N >> s;          /* twiddle W512^j = W1024^(2j) = cos/sin index j * 1024 / 2^s */
        for (; bf < e; ++bf) {
            unsigned j = bf & (hm - 1u), a = ((bf >> (s - 1u)) << s) + j, b = a + hm, t = j * tstep;
            float c = SPEC_COS[t], sn = SPEC_COS[(t + 768u) & 1023u];      /* sin(2 pi t / 1024) */
            float xr = st->re[b] * c + st->im[b] * sn, xi = st->im[b] * c - st->re[b] * sn;   /* W * z[b], W = c - i sn */
            st->re[b] = st->re[a] - xr; st->im[b] = st->im[a] - xi;
            st->re[a] += xr; st->im[a] += xi;
        }
        if (++st->step >= 36u) { st->step = 0; st->phase = SPLIT; }
        return;
    }
    if (st->phase == SPLIT) {                  /* X[k] = E - i W^k O, E/O from Z[k] and conj(Z[512-k]) */
        unsigned k = st->step * 128u, e = k + 128u;
        for (; k < e; ++k) {
            unsigned q = (HALF - k) & (HALF - 1u);
            float ar = st->re[k], ai = st->im[k], br = st->re[q], bi = -st->im[q];
            float er = 0.5f * (ar + br), ei = 0.5f * (ai + bi), orr = 0.5f * (ar - br), oi = 0.5f * (ai - bi);
            float c = SPEC_COS[k], sn = SPEC_COS[(k + 768u) & 1023u];
            float wr = orr * c + oi * sn, wi = oi * c - orr * sn;          /* W^k * O */
            float xr = er + wi, xi = ei - wr;                               /* E - i (W^k O) */
            st->pw[k] = xr * xr + xi * xi + 1e-20f;
        }
        if (++st->step >= 4u) {
            st->step = 0; st->phase = MAP;
            st->range = 30.0f + 60.0f * zoom_param_norm01(params[5], 0.5f);
            st->irange = rcp(st->range);
            st->fall = 0.006f + 0.09f * zoom_param_norm01(params[6], 0.4f);
            st->tilt = 6.0f * zoom_param_norm01(params[7], 0.5f);
        }
        return;
    }
    if (st->phase == MAP) {                    /* bins -> columns, in dB with tilt, then the falling bars */
        unsigned c = st->step * 21u, e = c + 21u;
        for (; c < e; ++c) {
            unsigned b0 = SPEC_B0[c], nb = SPEC_NB[c];
            float d, v;
            if (nb) {
                float p = st->pw[b0];
                for (i = 1; i < nb; ++i) if (st->pw[b0 + i] > p) p = st->pw[b0 + i];
                d = db10(p);
            } else {
                float f = (float)(int)SPEC_FR[c] * (1.0f / 255.0f);
                d = db10(st->pw[b0]) * (1.0f - f) + db10(st->pw[b0 + 1u]) * f;
            }
            d += st->tilt * SPEC_OCT[c] - REF_DB;
            v = (d + st->range) * st->irange;
            if (!(v > 0.0f)) v = 0.0f;
            if (v > 1.0f) v = 1.0f;
            if (v > st->lvl[c] - st->fall) st->lvl[c] = v; else st->lvl[c] -= st->fall;
            if (st->lvl[c] < 0.0f) st->lvl[c] = 0.0f;
            if (v >= st->pk[c]) { st->pk[c] = v; st->hold[c] = HOLD; }
            else if (st->hold[c]) st->hold[c]--;
            else { st->pk[c] -= st->fall * 0.5f; if (st->pk[c] < 0.0f) st->pk[c] = 0.0f; }
        }
        if (++st->step >= 6u) { st->step = 0; st->phase = DRAW; }
        return;
    }
    /* DRAW: wait for the last frame to be out, copy the background, then the bars in four parts. */
    if (st->z.phase != ZV_IDLE) return;
    if (st->step == 0u) { zv_copy(&st->z, SPEC_BG); st->step = 1; return; }
    {
        unsigned c = (st->step - 1u) * 32u, e = c + 32u > SPEC_COLS ? SPEC_COLS : c + 32u;
        for (; c < e; ++c) {
            int top = BOT - (int)(st->lvl[c] * (float)BAR_H + 0.5f), pk = BOT - (int)(st->pk[c] * (float)BAR_H + 0.5f);
            if (top <= BOT) vspan(&st->z, (int)c + 1, top, BOT);
            if (pk < top - 1) st->z.frame[(unsigned)(pk >> 3) * ZV_W + c + 1u] |= (unsigned char)(1u << (pk & 7));
        }
        if (++st->step < 5u) return;
    }
    zv_submit(&st->z);
    st->step = 0; st->phase = CAP;
}
