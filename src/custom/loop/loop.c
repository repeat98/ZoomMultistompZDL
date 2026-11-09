/* Loop v0.03: a looper for stock firmware (screen: MS-70CDR 2.10).
 *
 * The footswitch is the looper's button. Pressing it flips the effect on/off
 * (params[0]); every flip is a press, and the loop plays whether the effect
 * shows on or off:
 *   press         READY -> REC -> PLAY -> DUB -> PLAY -> DUB ...   STOP -> PLAY
 *   double press  stop (from PLAY / DUB / just closed); when stopped: clear
 * Undo (knob 4): flip it either way to undo the last overdub, again to redo.
 *
 * Mono loop of (L+R)/2, mixed into both outputs. Storage: 12-bit block float
 * (headroom to 8.0, so overdubs can pile up), 8 samples a block (one
 * callback), four blocks a 52-byte record (3 words of mantissas each, then four
 * shift bytes). Two buffers: an overdub pass reads the current loop and writes
 * the result into the other buffer for one full lap (more laps in place while
 * still overdubbing), so undo/redo is a buffer swap and nothing is ever copied.
 *
 * Memory: the effect's own arena (~5 s with undo). Long (knob 5,
 * experimental): adds the three regions of the MS-70CDR 2.10 OS that
 * MIDISTOMP's RAM test found unused (issue #19; 2,718,336 bytes; ~23 s with
 * undo); only on that firmware, not when MIDISTOMP is installed (its looper
 * uses them), and not if they overlap this effect's own arena.
 *
 * Quantize (0.02, knobs 6-8): Tempo (BPM, the knob's number), Beats (beats
 * per bar; 0 = off) and Click. With Beats set, the first press starts the
 * recording at once and starts bar 1 there; the closing press snaps the loop
 * to the nearest whole number of bars: pressed early, the recording runs on
 * to the bar line, then plays; pressed late, the overshoot is dropped and
 * playback carries on in time. Tempo and Beats are taken when recording
 * starts, so the loop and its click stay together. The click (an accent on
 * each bar) is added to the output only, never recorded: free-running while
 * the looper is empty, from the first press while recording, locked to the
 * loop while it plays, silent when stopped.
 *
 * Screen (zvis): state, time (with Beats set: the BPM when empty, else bar
 * and beat), the loop's waveform and a playhead. */
#include <stdint.h>
#include "zvis.h"
#include "loop_art.h"

extern unsigned int _Fx_DLY_Loop_Info[];

#define MAGIC      0x4C4F4F32u                 /* 'LOO2' (0.02 layout) */
#define FXID       467u
#define REC_BYTES  52u                         /* 4 blocks x (12 bytes of mantissas + 1 shift byte) */
#define DOUBLE_WIN 2480u                       /* 0.45 s of callbacks: a second press inside = double */
#define MIN_LEN    828u                        /* 0.15 s: a shorter loop was a mistaken press */
#define OV_MID     23                          /* waveform rows 13..33 */
#define OV_H       10
#define NOPOS      0xFFFFu
#define SR_X60     2646000.0f                  /* 44100 * 60: samples a beat = this / BPM */
#define CLK_DECAY  0.9975f                     /* click envelope per sample: ~9 ms */
#define CLK_C      1.9708433f                  /* 2 cos(2 pi 1200 / 44100): the beat click */
#define CLK_S      0.1701263f                  /* sin(2 pi 1200 / 44100) */
#define CLK_CA     1.8916480f                  /* 2 cos(2 pi 2000 / 44100): the bar accent */
#define CLK_SA     0.2811027f                  /* sin(2 pi 2000 / 44100) */

#ifndef LONG_R1                                /* the host test points these at its own buffers */
#define LONG_R1    0xC0102000u                 /* MS-70CDR 2.10, unused per MIDISTOMP's RAM test */
#define LONG_R2    0xC0198000u
#define LONG_R3    0xC0636980u
#endif

enum { READY, REC, PLAY, DUB, STOP };

typedef struct { uintptr_t base; unsigned recs; } Seg;

typedef struct {
    unsigned magic, mode, cur, len, pos, cap, half, nseg, longm, longok, lng;
    unsigned pass, lap, dub, pstart, newpass, undo_ok, presses, win, prev, on, kundo, klong;
    unsigned ovcol, step, colk, colk_rec;
    float lvl, dry, fade;
    /* quantize: q (beats a bar, 0 = off) and the beat in samples, both taken at
     * record start; target = blocks to record before closing (0 = none). */
    unsigned q, qk, target, tstop, beat, bib, due;   /* due: close the recording at the next callback's start */
    float qbeat, qinv, kbpm, gs, ce, cs1, cs2, cc, clk;
    Seg seg[4];
    unsigned char ov[2][ZV_W];                 /* waveform height per screen column, per buffer */
    ZvState z;
} LoopState;

ZV_INLINE(f2u)
static inline uint32_t f2u(float f) { union { float f; uint32_t u; } v; v.f = f; return v.u; }
ZV_INLINE(u2f)
static inline float u2f(uint32_t u) { union { float f; uint32_t u; } v; v.u = u; return v.f; }

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

/* Screen column scale: col = (pos * colk) >> 16 for pos in 0..n-1. */
ZV_INLINE(colk_of)
static inline unsigned colk_of(unsigned n) { return n ? (unsigned)(int)(8388608.0f * rcp((float)(int)n)) : 0u; }

/* The record holding block b of buffer buf. */
ZV_INLINE(rec_at)
static inline uint32_t *rec_at(LoopState *st, unsigned buf, unsigned b)
{
    unsigned r = buf * st->half + (b >> 2), k;
    for (k = 0; k + 1u < st->nseg && r >= st->seg[k].recs; ++k) r -= st->seg[k].recs;
    return (uint32_t *)(st->seg[k].base + r * REC_BYTES);
}

/* 8 samples -> 12-bit mantissas with a shared shift (block float). */
ZV_INLINE(enc_block)
static inline void enc_block(uint32_t *rec, unsigned sub, const float *x)
{
    float pk = 0.0f, scale;
    unsigned u[8], i;
    int sh;
    for (i = 0; i < 8u; ++i) { float a = x[i] < 0.0f ? -x[i] : x[i]; if (a > pk) pk = a; }
    sh = 126 - (int)((f2u(pk) >> 23) & 255u);  /* peak < 2^-sh: -3..12 = headroom to 8.0 for overdubs */
    if (sh > 12) sh = 12;
    if (sh < -3) sh = -3;
    scale = u2f((uint32_t)(127 + 11 + sh) << 23);
    for (i = 0; i < 8u; ++i) {
        float v = x[i] * scale;
        int m = (int)(v + (v >= 0.0f ? 0.5f : -0.5f));
        if (m > 2047) m = 2047;
        if (m < -2047) m = -2047;
        u[i] = (unsigned)m & 0xFFFu;
    }
    rec += 3u * sub;
    rec[0] = u[0] | (u[1] << 12) | (u[2] << 24);
    rec[1] = (u[2] >> 8) | (u[3] << 4) | (u[4] << 16) | (u[5] << 28);
    rec[2] = (u[5] >> 4) | (u[6] << 8) | (u[7] << 20);
    ((unsigned char *)(rec - 3u * sub))[48u + sub] = (unsigned char)(sh + 3);
}

ZV_INLINE(dec_block)
static inline void dec_block(const uint32_t *rec, unsigned sub, float *y)
{
    int sh = (int)(((const unsigned char *)rec)[48u + sub] & 15u) - 3;
    float inv = u2f((uint32_t)(127 - 11 - sh) << 23);
    uint32_t w0 = rec[3u * sub], w1 = rec[3u * sub + 1u], w2 = rec[3u * sub + 2u];
    unsigned u[8], i;
    u[0] = w0 & 0xFFFu; u[1] = (w0 >> 12) & 0xFFFu; u[2] = (w0 >> 24) | ((w1 & 0xFu) << 8);
    u[3] = (w1 >> 4) & 0xFFFu; u[4] = (w1 >> 16) & 0xFFFu; u[5] = (w1 >> 28) | ((w2 & 0xFFu) << 4);
    u[6] = (w2 >> 8) & 0xFFFu; u[7] = (w2 >> 20) & 0xFFFu;
    for (i = 0; i < 8u; ++i) y[i] = (float)(((int)(u[i] << 20)) >> 20) * inv;
}

/* Waveform: the peak of a block into its screen column. */
ZV_INLINE(ov_put)
static inline void ov_put(LoopState *st, unsigned buf, unsigned col, const float *w)
{
    float pk = 0.0f;
    unsigned i, h;
    for (i = 0; i < 8u; ++i) { float a = w[i] < 0.0f ? -w[i] : w[i]; if (a > pk) pk = a; }
    h = (unsigned)(int)(pk * 16.0f + 0.5f);
    if (h > (unsigned)OV_H) h = OV_H;
    if (col >= (unsigned)ZV_W) col = ZV_W - 1;
    if (col != st->ovcol) { st->ovcol = col; st->ov[buf][col] = 0; }
    if (h > st->ov[buf][col]) st->ov[buf][col] = (unsigned char)h;
}

/* Where the loop lives: the arena after the state, plus the Long regions. */
ZV_INLINE(layout)
static inline void layout(LoopState *st, uintptr_t end)
{
    uintptr_t a = ((uintptr_t)st + sizeof(LoopState) + 7u) & ~(uintptr_t)7u;
    unsigned total;
    st->seg[0].base = a; st->seg[0].recs = (unsigned)((end - a) / REC_BYTES);
    st->nseg = 1; st->longm = 0;
    if (st->lng && st->longok) {
        st->seg[1].base = LONG_R1; st->seg[1].recs = 614400u / REC_BYTES;
        st->seg[2].base = LONG_R2; st->seg[2].recs = 425984u / REC_BYTES;
        st->seg[3].base = LONG_R3; st->seg[3].recs = 1677952u / REC_BYTES;
        st->nseg = 4; st->longm = 1;
    }
    total = st->seg[0].recs + (st->longm ? st->seg[1].recs + st->seg[2].recs + st->seg[3].recs : 0u);
    st->half = total >> 1;
    st->cap = st->half * 4u;
    st->colk_rec = colk_of(st->cap);
}

/* May the Long regions be used? MS-70CDR 2.10 only, MIDISTOMP absent (its
 * services block at 0xC00F3000 holds the region bases), no overlap with our
 * own arena. Pure reads. */
ZV_INLINE(long_ok)
static inline int long_ok(uintptr_t base, uintptr_t end)
{
    unsigned k;
#ifdef LOOP_TEST_LONG
    return 1;
#endif
    if (!zv_fw_ok()) return 0;
    for (k = 2; k < 8u; ++k) {
        unsigned v = ZV_U32(0xC00F3000u + 4u * k);
        if (v == 0xC0102000u || v == 0xC0198000u || v == 0xC0636980u) return 0;
    }
    if (end > 0xC0102000u && base < 0xC0200000u) return 0;    /* regions 1-2: 0xC0102000..0xC01FFFFF */
    if (end > 0xC0636980u && base < 0xC0650400u) return 0;    /* region 3 */
    return 1;
}

/* Recording ends with `len` blocks; playback goes on at block `at`. */
ZV_INLINE(finish)
static inline void finish(LoopState *st, unsigned len, unsigned at)
{
    unsigned c, cols;
    if (st->q) {   /* hand the click on from the recording's grid to the loop's */
        unsigned tb = (unsigned)(int)((float)(int)len * 8.0f * st->qinv + 0.5f);
        st->beat = (st->beat != 0xFFFFFFFFu && st->beat >= tb) ? st->beat - tb : 0xFFFFFFFFu;
    }
    st->len = len; st->pos = at; st->target = 0;
    st->mode = st->tstop ? STOP : PLAY;
    if (st->tstop) st->pos = 0;
    st->tstop = 0;
    st->colk = colk_of(st->len);
    cols = (st->len * st->colk_rec) >> 16;     /* the recording's waveform, stretched to the screen */
    for (c = ZV_W; c-- > 0u;) st->ov[st->cur][c] = st->ov[st->cur][(c * cols) >> 7];
}

/* Blocks in n bars (rounded to the 8-sample block). */
ZV_INLINE(bars_len)
static inline unsigned bars_len(const LoopState *st, int n)
{
    return (unsigned)(int)((float)n * (float)(int)st->q * st->qbeat * 0.125f + 0.5f);
}

/* The closing press (or a full memory). Free: the loop is what was recorded.
 * Quantized: the nearest whole number of bars, at least one and within the
 * memory; shorter than the recording drops the overshoot (playback goes on
 * past the bar line, in time), longer records on to the bar line. */
ZV_INLINE(close_loop)
static inline void close_loop(LoopState *st)
{
    unsigned L;
    int n;
    if (!st->q) {
        if (st->pos < MIN_LEN) { st->mode = READY; st->len = 0; st->tstop = 0; return; }
        finish(st, st->pos, 0);
        return;
    }
    n = (int)((float)(int)st->pos * 8.0f * st->qinv * rcp((float)(int)st->q) + 0.5f);
    if (n < 1) n = 1;
    L = bars_len(st, n);
    while (n > 1 && L > st->cap) L = bars_len(st, --n);
    if (L > st->cap) {                         /* not even one bar fits: keep what there is */
        if (st->pos < MIN_LEN) { st->mode = READY; st->len = 0; st->tstop = 0; return; }
        finish(st, st->pos, 0);
        return;
    }
    if (L > st->pos) { st->target = L; return; }   /* record on to the bar line */
    finish(st, L, st->pos - L);
}

ZV_INLINE(single_press)
static inline void single_press(LoopState *st)
{
    unsigned m = st->mode;
    st->newpass = 0;
    if (m == READY) {
        unsigned c;
        st->mode = REC; st->pos = 0; st->len = 0; st->cur = 0; st->undo_ok = 0; st->pass = 0; st->dub = 0;
        st->ovcol = NOPOS; st->target = 0; st->tstop = 0;
        st->q = st->qk;                        /* this loop's grid: bar 1 starts now */
        st->qbeat = SR_X60 * rcp(st->kbpm); st->qinv = st->kbpm * (1.0f / SR_X60);
        st->gs = 0.0f; st->beat = 0xFFFFFFFFu; st->bib = 0;
        for (c = 0; c < (unsigned)ZV_W; ++c) st->ov[0][c] = 0;
    } else if (m == REC) { if (!st->target) st->due = 1; }
    else if (m == PLAY) {
        st->mode = DUB; st->dub = 1;
        if (!st->pass) {
            unsigned c;
            st->pass = 1; st->lap = 0; st->pstart = st->pos; st->undo_ok = 0; st->ovcol = NOPOS; st->newpass = 1;
            for (c = 0; c < (unsigned)ZV_W; ++c) st->ov[st->cur ^ 1u][c] = st->ov[st->cur][c];   /* the new take starts as the old */
        }
    } else if (m == DUB) { st->mode = PLAY; st->dub = 0; }
    else { st->mode = PLAY; if (!st->pass) st->pos = 0; }
}

/* The second press of a double: `prev` is the state before the first one. */
ZV_INLINE(double_press)
static inline void double_press(LoopState *st, unsigned prev)
{
    if (st->mode == READY) return;              /* the first press cancelled a too-short loop */
    if (prev == READY) { st->mode = READY; st->len = 0; st->target = 0; return; }
    if (st->target) { st->tstop = 1; return; }  /* recording on to the bar line: stop there */
    if (prev == STOP) { st->mode = READY; st->len = 0; st->pass = 0; st->dub = 0; st->undo_ok = 0; return; }
    if (prev == PLAY && st->newpass) st->pass = 0;   /* drop the overdub the first press began */
    st->dub = 0; st->mode = STOP;
    if (!st->pass) st->pos = 0;                 /* a finishing pass runs on silently, then rests at 0 */
}

ZV_INLINE(undo)
static inline void undo(LoopState *st)
{
    if (st->mode == READY || st->mode == REC) return;
    if (st->pass) { st->pass = 0; st->dub = 0; st->undo_ok = 0; if (st->mode == DUB) st->mode = PLAY; }
    else if (st->undo_ok) st->cur ^= 1u;
}

/* Vertical span of rows y0..y1 in column x: set (black) or flipped. */
ZV_INLINE(vspan)
static inline void vspan(ZvState *z, int x, int y0, int y1, int flip)
{
    int b;
    if ((unsigned)x >= (unsigned)ZV_W) return;
    for (b = y0 >> 3; b <= y1 >> 3; ++b) {
        int lo = b == y0 >> 3 ? y0 & 7 : 0, hi = b == y1 >> 3 ? y1 & 7 : 7;
        unsigned char m = (unsigned char)((0xFFu << lo) & (0xFFu >> (7 - hi)));
        unsigned char *p = &z->frame[b * ZV_W + x];
        *p = flip ? (unsigned char)(*p ^ m) : (unsigned char)(*p | m);
    }
}

/* A header sprite (2 bytes a column: block rows 0 and 1) at column x. */
ZV_INLINE(put2)
static inline void put2(ZvState *z, const unsigned char *s, int w, int x)
{
    int c;
    for (c = 0; c < w; ++c)
        if ((unsigned)(x + c) < (unsigned)ZV_W) { z->frame[x + c] |= s[2 * c]; z->frame[ZV_W + x + c] |= s[2 * c + 1]; }
}

#pragma CODE_SECTION(Fx_DLY_Loop, ".audio")
void Fx_DLY_Loop(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    unsigned int *info = _Fx_DLY_Loop_Info;
    float onv = params[0];                     /* read first: not after zv_service's loops */
    uintptr_t base, end;
    LoopState *st;
    float in[8], y[8], ck[8];
    unsigned i;
    int visible;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(LoopState) + 64u * REC_BYTES) return;
    st = (LoopState *)base;
    if (st->magic != MAGIC) {
        st->magic = MAGIC; st->mode = READY; st->cur = 0; st->len = 0; st->pos = 0; st->pass = 0; st->dub = 0;
        st->undo_ok = 0; st->presses = 0; st->win = 0; st->prev = READY; st->newpass = 0; st->step = 0;
        st->on = onv >= 0.5f; st->kundo = 0xFFu; st->klong = 0xFFu; st->ovcol = NOPOS; st->colk = 0;
        st->lvl = 1.0f; st->dry = 1.0f; st->fade = 1.0f;
        st->q = 0; st->qk = 0; st->target = 0; st->tstop = 0; st->due = 0; st->beat = 0xFFFFFFFFu; st->bib = 0;
        st->kbpm = 120.0f; st->qbeat = SR_X60 / 120.0f; st->qinv = 120.0f / SR_X60;
        st->gs = 0.0f; st->ce = 0.0f; st->cs1 = 0.0f; st->cs2 = 0.0f; st->cc = CLK_C; st->clk = 0.0f;
        st->longok = (unsigned)long_ok(base, end); st->lng = 0;
        for (i = 0; i < (unsigned)ZV_W; ++i) { st->ov[0][i] = 0; st->ov[1][i] = 0; }
        layout(st, end);
        zv_init(&st->z, FXID, info);
        return;
    }

    {   /* knobs and the footswitch */
        int on = onv >= 0.75f ? 1 : onv <= 0.25f ? 0 : (int)st->on;   /* the bypass value may fade */
        unsigned ku = (unsigned)(int)(zoom_param_norm01(params[8], 0.0f) * 100.0f + 0.5f) != 0u;
        unsigned kl = (unsigned)(int)(zoom_param_norm01(params[9], 0.0f) * 100.0f + 0.5f) != 0u;
        st->lvl = zoom_param_norm01(params[5], 1.0f);
        st->dry = zoom_param_norm01(params[6], 1.0f);
        st->fade = zoom_param_norm01(params[7], 1.0f);
        {   /* knobs 6-8 arrive as raw/100: Tempo is the BPM, Beats 0 = off */
            float t = params[10] * 100.0f, b = params[11] * 100.0f;
            if (!(t >= 40.0f)) t = !(t >= 0.0f && t <= 300.0f) ? 120.0f : 40.0f;
            if (t > 250.0f) t = 250.0f;
            st->kbpm = (float)(int)(t + 0.5f);
            st->qk = (b >= 0.5f && b <= 12.5f) ? (unsigned)(int)(b + 0.5f) : 0u;
            st->clk = zoom_param_norm01(params[12], 0.5f);
        }
        if (st->win) { if (--st->win == 0u) st->presses = 0; }
        if ((unsigned)on != st->on) {
            st->on = (unsigned)on;
            if (st->presses == 1u && st->win) { double_press(st, st->prev); st->presses = 0; st->win = 0; }
            else { st->prev = st->mode; single_press(st); st->presses = 1; st->win = DOUBLE_WIN; }
        }
        /* The one place a recording closes (press, bar line, full memory): one
         * inlined copy of close_loop / finish. The block that asked was the
         * last recorded; the loop plays from this block on, so no timing is lost. */
        if (st->due) {
            st->due = 0;
            if (st->mode == REC) {
                if (st->target && st->pos >= st->target) finish(st, st->target, 0);
                else if (!st->target) close_loop(st);
                else if (st->pos >= st->cap) { st->target = 0; close_loop(st); }
            }
        }
        if (ku != st->kundo) { if (st->kundo != 0xFFu) undo(st); st->kundo = ku; }
        if (kl != st->klong) {
            st->klong = kl;
            if (st->mode == READY) { st->lng = kl; layout(st, end); }
        }
        if (st->mode == READY && st->lng != st->klong) { st->lng = st->klong; layout(st, end); }
    }

    for (i = 0; i < 8u; ++i) { in[i] = (fx[i] + fx[i + 8]) * 0.5f; y[i] = 0.0f; }
    {   /* the click, on the loop's grid (from the block's state before it plays);
         * READY: free-running at the knobs' tempo. Added to the output, not recorded. */
        unsigned beats = st->mode == READY ? st->qk : st->q, tb = 0xFFFFFFFFu;
        int on = beats && st->clk > 0.0f && st->mode != STOP;
        float inv = st->mode == READY ? st->kbpm * (1.0f / SR_X60) : st->qinv, g0, bar = 0.0f, rb = 0.0f;
        if (on) {
            rb = rcp((float)(int)beats);
            bar = (float)(int)beats * SR_X60 * rcp(st->kbpm);
            if (st->mode == READY) g0 = st->gs;
            else {
                g0 = (float)(int)st->pos * 8.0f;  /* this block: since the first press, or of the loop */
                if (st->mode != REC) tb = (unsigned)(int)((float)(int)st->len * 8.0f * inv + 0.5f);   /* beats in the loop */
            }
        } else g0 = 0.0f;
        for (i = 0; i < 8u; ++i) {
            float c = 0.0f;
            if (on) {
                float g = g0 + (float)(int)i;
                unsigned bt;
                if (st->mode == READY && g >= bar) g -= bar;
                bt = (unsigned)(int)(g * inv);
                if (bt >= tb) bt = tb - 1u;     /* rounding sliver before the loop wraps */
                if (bt != st->beat) {          /* a new beat: restart the click, accent on the bar */
                    unsigned k = (unsigned)(int)((float)(int)bt * rb + 1.0e-4f);
                    st->beat = bt;
                    st->bib = bt - k * beats;
                    st->cc = st->bib ? CLK_C : CLK_CA;
                    st->cs1 = 0.0f; st->cs2 = st->bib ? -CLK_S : -CLK_SA; st->ce = 1.0f;
                }
            } else st->beat = 0xFFFFFFFFu;
            if (st->ce > 0.0f) {
                float v = st->cc * st->cs1 - st->cs2;
                st->cs2 = st->cs1; st->cs1 = v;
                c = v * st->ce * st->clk * 0.5f;
                st->ce *= CLK_DECAY;
                if (st->ce < 1.0e-4f) { st->ce = 0.0f; st->cs1 = 0.0f; st->cs2 = 0.0f; }
            }
            ck[i] = c;
        }
        if (st->mode == READY && on) { st->gs += 8.0f; if (st->gs >= bar) st->gs -= bar; }
    }

    if (st->mode == REC && !st->due) {
        enc_block(rec_at(st, st->cur, st->pos), st->pos & 3u, in);
        ov_put(st, st->cur, (st->pos * st->colk_rec) >> 16, in);
        ++st->pos;
        if ((st->target && st->pos >= st->target) || st->pos >= st->cap) st->due = 1;   /* closes next callback */
    } else if (st->len && st->mode != READY && (st->mode != STOP || st->pass)) {
        unsigned dst = st->cur ^ 1u;
        dec_block(rec_at(st, st->pass && st->lap ? dst : st->cur, st->pos), st->pos & 3u, y);
        if (st->pass) {
            float w[8];
            for (i = 0; i < 8u; ++i) w[i] = st->dub ? y[i] * st->fade + in[i] : y[i];
            enc_block(rec_at(st, dst, st->pos), st->pos & 3u, w);
            ov_put(st, dst, (st->pos * st->colk) >> 16, w);
        }
        if (++st->pos >= st->len) st->pos = 0;
        if (st->pass && st->pos == st->pstart) {
            if (st->dub) st->lap = 1;          /* still overdubbing: next lap in place */
            else { st->cur = dst; st->pass = 0; st->undo_ok = 1; if (st->mode == STOP) st->pos = 0; }
        }
        if (st->mode == STOP) for (i = 0; i < 8u; ++i) y[i] = 0.0f;
    }
    for (i = 0; i < 8u; ++i) {
        float p = y[i] * st->lvl + ck[i];
        fx[i] = fx[i] * st->dry + p;
        fx[i + 8] = fx[i + 8] * st->dry + p;
    }

    /* the screen */
    visible = zv_visible(&st->z, ctx);
    zv_service(&st->z, info, visible);
    if (!visible) { st->step = 0; return; }
    if (st->z.phase != ZV_IDLE) return;
    if (st->step == 0u) {
        for (i = 0; i < 1024u; ++i) st->z.frame[i] = LOOP_BG[i];
        st->step = 1;
        return;
    }
    if (st->step == 1u) {                      /* state, time, tags */
        unsigned t = st->mode == READY ? st->cap : st->mode == REC ? st->pos : st->len;
        unsigned t10 = (unsigned)(int)((float)(int)t * 0.0018140590f), d2 = t10 / 100u, d1 = (t10 / 10u) % 10u, d0 = t10 % 10u;
        int x = ZV_W - 1 - LOOP_GW * (d2 ? 5 : 4);
        unsigned qb = st->mode == READY ? st->qk : st->q;
        put2(&st->z, LOOP_WORDS + LOOP_WORD_AT[st->mode], (int)LOOP_WORD_W[st->mode], 1);
        if (qb && st->mode == READY) {         /* quantize, empty: the tempo */
            unsigned b = (unsigned)(int)st->kbpm;
            d2 = b / 100u; d1 = (b / 10u) % 10u; d0 = b % 10u;
            x = ZV_W - 1 - LOOP_GW * (d2 ? 3 : 2);
            if (d2) { put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d2, LOOP_GW, x); x += LOOP_GW; }
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d1, LOOP_GW, x); x += LOOP_GW;
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d0, LOOP_GW, x);
        } else if (qb) {                       /* quantize: bar.beat, from 1 */
            unsigned bt = (unsigned)(int)((float)(int)st->pos * 8.0f * st->qinv);
            unsigned k = (unsigned)(int)((float)(int)bt * rcp((float)(int)qb) + 1.0e-4f);
            unsigned bar = k + 1u, beat = bt - k * qb + 1u;
            if (bar > 99u) bar = 99u;
            d1 = bar / 10u; d0 = bar % 10u;
            x = ZV_W - 1 - LOOP_GW * ((d1 ? 2 : 1) + 2 + (beat > 9u ? 1 : 0));
            if (d1) { put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d1, LOOP_GW, x); x += LOOP_GW; }
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d0, LOOP_GW, x); x += LOOP_GW;
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * 10u, LOOP_GW, x); x += LOOP_GW;   /* . */
            if (beat > 9u) { put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * 1u, LOOP_GW, x); x += LOOP_GW; beat -= 10u; }
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * beat, LOOP_GW, x);
        } else {
            if (d2) { put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d2, LOOP_GW, x); x += LOOP_GW; }
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d1, LOOP_GW, x); x += LOOP_GW;
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * 10u, LOOP_GW, x); x += LOOP_GW;   /* . */
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * d0, LOOP_GW, x); x += LOOP_GW;
            put2(&st->z, LOOP_GLYPHS + 2u * LOOP_GW * 11u, LOOP_GW, x);                  /* S */
        }
        if (st->undo_ok) put2(&st->z, LOOP_TAGS + LOOP_TAG_AT[0], (int)LOOP_TAG_W[0], LOOP_TAG_X);
        if (st->longm) put2(&st->z, LOOP_TAGS + LOOP_TAG_AT[1], (int)LOOP_TAG_W[1], LOOP_TAG_X);
        else if (st->klong == 1u) {            /* NO LONG: unavailable; CLEAR: available once the looper is empty */
            unsigned t = st->longok ? 3u : 2u;
            put2(&st->z, LOOP_TAGS + LOOP_TAG_AT[t], (int)LOOP_TAG_W[t], LOOP_TAG_X);
        }
        st->step = 2;
        return;
    }
    {                                          /* waveform, 32 columns a callback, then the playhead */
        unsigned show = st->pass ? st->cur ^ 1u : st->cur, c, c0 = (st->step - 2u) * 32u;
        if (st->mode != READY)
            for (c = c0; c < c0 + 32u; ++c) {
                int h = st->ov[show][c];
                vspan(&st->z, (int)c, OV_MID - h, OV_MID + h, 0);
            }
        if (++st->step < 6u) return;
        if (st->mode == REC) vspan(&st->z, (int)((st->pos * st->colk_rec) >> 16), OV_MID - OV_H, OV_MID + OV_H, 1);
        else if (st->len && st->mode != READY && (st->mode != STOP || st->pass))
            vspan(&st->z, (int)((st->pos * st->colk) >> 16), OV_MID - OV_H, OV_MID + OV_H, 1);
        zv_submit(&st->z);
        st->step = 0;
    }
}

/* Knob labels (pedal and PE): Tempo shows the BPM it plays (40..250), Beats
 * shows Off at 0. No divide helper: constant divisions only. */
ZV_INLINE(label_num)
static inline int label_num(unsigned v, char *out)
{
    int n = 0;
    if (v >= 100u) out[n++] = (char)('0' + v / 100u);
    if (v >= 10u) out[n++] = (char)('0' + (v / 10u) % 10u);
    out[n++] = (char)('0' + v % 10u);
    out[n] = 0;
    return n;
}

int ZDL_GetLabel_5(unsigned int value, char *out)
{
    return label_num(value < 40u ? 40u : value > 250u ? 250u : value, out);
}

int ZDL_GetLabel_6(unsigned int value, char *out)
{
    if (!value) { out[0] = 'O'; out[1] = 'f'; out[2] = 'f'; out[3] = 0; return 3; }
    return label_num(value, out);
}
