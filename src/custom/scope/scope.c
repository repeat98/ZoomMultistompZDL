/* Scope: a live oscilloscope on the pedal screen (MS-70CDR SYSTEM 2.10).
 *
 * Audio passes through untouched. While its own main card is on screen
 * (zv_visible), each frame: wait for a rising zero crossing (or free-run),
 * capture 128 columns of `spc` samples -- min/max of (L+R)/2 (Wave) or L
 * against R as points (XY) -- then draw them over the static background in four
 * steps and hand the frame to zvis, which encodes and shows it (~30 fps).
 * Full screen (0.03): the plot uses all 64 rows and the knob boxes are hidden.
 * See ../common/zvis.h for the firmware side and its rules. */
#include <stdint.h>
#include "zvis.h"
#include "scope_art.h"

extern unsigned int _Fx_DLY_Scope_Info[];

#define MAGIC   0x53434F52u                    /* 'SCOR' (v0.03 layout: 64 rows) */
#define FXID    414u
#define PH      SCOPE_PLOT_H
#define TOP     1
#define BOT     ((int)PH - 2)
#define MID     ((float)(TOP + BOT) * 0.5f)
#define HALF    ((float)(BOT - TOP) * 0.5f)
#define FREE_RUN 4096u

enum { ARM, TRIG, CAPTURE, COPY, DRAW };

typedef struct {
    unsigned magic, phase, col, k, spc, wait, xy, step;
    float last, gain;
    unsigned char lo[ZV_W], hi[ZV_W];
    unsigned char dots[8 * ZV_W];              /* XY: raw column bytes, rows 0..63 */
    ZvState z;
} ScopeState;

ZV_INLINE(row_of)
static inline int row_of(float s, float g)
{
    float y = MID - s * g * HALF;
    if (!(y >= (float)TOP)) return TOP;
    if (y > (float)BOT) return BOT;
    return (int)(y + 0.5f);
}

ZV_INLINE(span_bits)
static inline unsigned span_bits(int lo, int hi, int b)
{
    int a = lo - 8 * b, e = hi - 8 * b;
    if (e < 0 || a > 7) return 0;
    if (a < 0) a = 0;
    if (e > 7) e = 7;
    return (0xFFu >> (7 - e)) & (0xFFu << a) & 0xFFu;
}

#pragma CODE_SECTION(Fx_DLY_Scope, ".audio")
void Fx_DLY_Scope(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    unsigned int *info = _Fx_DLY_Scope_Info;
    uintptr_t base, end;
    ScopeState *st;
    unsigned i;
    int visible;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(ScopeState)) return;
    st = (ScopeState *)base;
    if (st->magic != MAGIC) { st->magic = MAGIC; st->phase = ARM; zv_init(&st->z, FXID, info); return; }

    visible = zv_visible(&st->z, ctx);
    zv_service(&st->z, info, visible);
    /* Full screen: the firmware's knob boxes hidden, again every callback (they
     * can come back after our first callback; idempotent, see Skull). */
    zv_hide_knob_boxes(&st->z, info);
    if (params[0] < 0.5f || !visible) { st->phase = ARM; return; }   /* off or not on screen: no work */
    if (st->z.phase != ZV_IDLE) return;                              /* frame still being published */

    if (st->phase == ARM) {
        float t = zoom_param_norm01(params[5], 0.3f);
        float g = zoom_param_norm01(params[6], 0.25f);
        st->spc = 1u + (unsigned)(int)(t * t * 63.0f);              /* via int: no RTS helper */
        st->gain = 0.5f * (1.0f + g * g * 63.0f);
        /* Handlers deliver raw/100: Mode's 0/1 arrives as 0/0.01 (as Stasis reads it). */
        st->xy = (int)(zoom_param_norm01(params[7], 0.0f) * 100.0f + 0.5f) != 0;
        st->wait = 0; st->col = 0; st->k = 0; st->last = 0.0f;
        for (i = 0; i < ZV_W; ++i) { st->lo[i] = (unsigned char)BOT; st->hi[i] = (unsigned char)TOP; }
        for (i = 0; i < 8u * ZV_W; ++i) st->dots[i] = 0;
        st->phase = st->xy ? CAPTURE : TRIG;
    }
    if (st->phase == TRIG) {
        for (i = 0; i < 8u && st->phase == TRIG; ++i) {
            float s = (fx[i] + fx[i + 8]) * 0.5f;
            if (st->last < -0.002f && s >= 0.0f) st->phase = CAPTURE;
            if (s < -0.002f || s > 0.002f) st->last = s;
            if (++st->wait >= FREE_RUN) st->phase = CAPTURE;
        }
        return;
    }
    if (st->phase == CAPTURE) {
        for (i = 0; i < 8u && st->phase == CAPTURE; ++i) {
            float l = fx[i], r = fx[i + 8];
            if (st->xy) {
                float xf = 64.0f + l * st->gain * 63.0f;
                int x = xf < 0.0f ? 0 : xf > 127.0f ? 127 : (int)xf;
                int y = row_of(r, st->gain);
                st->dots[(unsigned)(y >> 3) * ZV_W + (unsigned)x] |= (unsigned char)(1u << (y & 7));
                if (++st->k >= st->spc * 8u) { st->k = 0; if (++st->col >= ZV_W) st->phase = COPY; }
            } else {
                int y = row_of((l + r) * 0.5f, st->gain);
                if (y < st->lo[st->col]) st->lo[st->col] = (unsigned char)y;
                if (y > st->hi[st->col]) st->hi[st->col] = (unsigned char)y;
                if (++st->k >= st->spc) {
                    st->k = 0;
                    if (++st->col >= ZV_W) st->phase = COPY;
                    else { st->lo[st->col] = (unsigned char)y; st->hi[st->col] = (unsigned char)y; }
                }
            }
        }
        return;
    }
    if (st->phase == COPY) { zv_copy(&st->z, SCOPE_BG); st->step = 0; st->phase = DRAW; return; }
    /* DRAW: 32 columns per callback. */
    {
        unsigned c0 = st->step * 32u, c;
        int b;
        for (c = c0; c < c0 + 32u; ++c) {
            if (st->xy) {
                for (b = 0; b < 8; ++b) st->z.frame[(unsigned)b * ZV_W + c] |= st->dots[(unsigned)b * ZV_W + c];
            } else {
                int lo = st->lo[c], hi = st->hi[c];
                if (c) {                                     /* join to the previous column */
                    int pl = st->lo[c - 1], ph = st->hi[c - 1];
                    if (ph < lo) lo = ph;
                    if (pl > hi) hi = pl;
                }
                for (b = lo >> 3; b <= (hi >> 3); ++b)
                    st->z.frame[(unsigned)b * ZV_W + c] |= (unsigned char)span_bits(lo, hi, b);
            }
        }
        if (++st->step >= 4u) { zv_submit(&st->z); st->phase = ARM; }
    }
}

/* Knob 3 shows its mode by name. */
int ZDL_GetLabel_2(unsigned int value, char *out)
{
    if (value) { out[0] = 'X'; out[1] = 'Y'; out[2] = 0; return 2; }
    out[0] = 'W'; out[1] = 'a'; out[2] = 'v'; out[3] = 'e'; out[4] = 0; return 4;
}
