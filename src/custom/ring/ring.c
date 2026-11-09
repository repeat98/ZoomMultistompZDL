/* Ring: a rotating ring oscilloscope on the pedal screen (MS-70CDR 2.10).
 *
 * Audio passes through untouched. While its own main card is on screen, each
 * frame waits for a rising zero crossing (or free-runs), takes 128 points of
 * `spc` samples each, and draws them around a circle -- radius = base + signal
 * -- as a closed white line on the black panel, rotated a little more every
 * frame. 32 segments per callback, then zvis encodes and shows it (~30 fps).
 * The LCD's pixels are ~1.4x taller than wide, so x radii are stretched by 1.4
 * to look round. See ../common/zvis.h. */
#include <stdint.h>
#include "zvis.h"
#include "ring_art.h"

extern unsigned int _Fx_DLY_Ring_Info[];

#define MAGIC    0x52494E47u                   /* 'RING' */
#define FXID     415u
#define N        128u                          /* points around the ring */
#define CX       64
#define CY       31                            /* full screen, rows 0..63 (0.02) */
#define R0       17.0f                         /* base radius (rows) */
#define RMIN     3.0f
#define RMAX     30.0f
#define ASPECT   1.4f
#define FREE_RUN 1024u                       /* keep spinning at ~30 fps in silence */

enum { ARM, TRIG, CAPTURE, COPY, DRAW };

typedef struct {
    unsigned magic, phase, n, k, spc, wait, step, rot;
    float last, size;
    short px[N], py[N];                        /* ring points for this frame */
    float v[N];                                /* captured signal per point */
    ZvState z;
} RingState;

#pragma CODE_SECTION(Fx_DLY_Ring, ".audio")
void Fx_DLY_Ring(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    unsigned int *info = _Fx_DLY_Ring_Info;
    uintptr_t base, end;
    RingState *st;
    unsigned i;
    int visible;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(RingState)) return;
    st = (RingState *)base;
    if (st->magic != MAGIC) { st->magic = MAGIC; st->phase = ARM; st->rot = 0; zv_init(&st->z, FXID, info); return; }

    visible = zv_visible(&st->z, ctx);
    zv_service(&st->z, info, visible);
    /* Full screen: the firmware's knob boxes hidden, again every callback (they
     * can come back after our first callback; idempotent, see Skull). */
    zv_hide_knob_boxes(&st->z, info);
    if (params[0] < 0.5f || !visible) { st->phase = ARM; return; }
    if (st->z.phase != ZV_IDLE) return;

    if (st->phase == ARM) {
        float t = zoom_param_norm01(params[5], 0.25f);
        float g = zoom_param_norm01(params[6], 0.35f);
        float spin = zoom_param_norm01(params[7], 0.6f);
        st->spc = 1u + (unsigned)(int)(t * t * 63.0f);              /* via int: no RTS helper */
        st->size = 2.0f + g * g * 60.0f;
        st->rot = (st->rot + (unsigned)(int)((spin - 0.5f) * 16.0f + 256.0f)) & 255u;
        st->wait = 0; st->n = 0; st->k = 0; st->last = 0.0f;
        st->phase = TRIG;
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
            if (st->k == 0u) st->v[st->n] = (fx[i] + fx[i + 8]) * 0.5f;   /* one sample per point: no division */
            if (++st->k >= st->spc) { st->k = 0; if (++st->n >= N) st->phase = COPY; }
        }
        return;
    }
    if (st->phase == COPY) {
        zv_copy(&st->z, RING_BG);
        for (i = 0; i < N; ++i) {               /* place the points: radius = base + signal */
            float r = R0 + st->v[i] * st->size * 13.0f;   /* x1.4 with the full-screen radius */
            unsigned a = (i * 2u + st->rot) & 255u;
            if (!(r >= RMIN)) r = RMIN;
            if (r > RMAX) r = RMAX;
            st->px[i] = (short)(CX + (int)(r * ASPECT * (float)RING_COS[a] * (1.0f / 16384.0f)));
            st->py[i] = (short)(CY - (int)(r * (float)RING_COS[(a + 192u) & 255u] * (1.0f / 16384.0f)));
        }
        st->step = 0; st->phase = DRAW;
        return;
    }
    /* DRAW: 32 segments per callback, closed ring, white on black. */
    {
        unsigned s0 = st->step * 32u;
        for (i = s0; i < s0 + 32u; ++i) {
            unsigned j = (i + 1u) & (N - 1u);
            zv_line(&st->z, st->px[i], st->py[i], st->px[j], st->py[j], 0);
        }
        if (++st->step >= N / 32u) { zv_submit(&st->z); st->phase = ARM; }
    }
}
