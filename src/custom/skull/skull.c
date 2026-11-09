/* Skull v0.05: a shaded 3D skull that reacts to the signal, idles with
 * animations when it's quiet, and explodes at the loudest (MS-70CDR 2.10).
 *
 * Audio passes through untouched. A fast-attack follower (release set by
 * Decay) drives it: the jaw opens through SKULL_JAW_STEPS pre-rendered frames
 * (our own 3D model, lit and dithered: skull3d.py), the eye lights grow and
 * flicker with level, and a sharp attack jolts it sideways. Full screen: the
 * knob boxes are hidden, re-checked every callback (zv_hide_knob_boxes, experimental).
 *
 * Quiet for ~3 s, it idles, one animation every ~2.5 s, in turn: looks around,
 * spins, a snake crawls out of one eye socket through the mouth and out of
 * the other, rolls, melts into dust that piles up and re-forms. Playing
 * brings the face straight back.
 *
 * At the very loudest (Boom) it explodes: a white flash, a negative, the
 * screen shakes, the skull breaks into shards (triangles cut from its own
 * picture) that tumble, fall and bounce, with sparks and shockwaves; then they
 * fly home. It re-arms once the level drops.
 *
 * Frames are stored compressed (build.py lz_row) and decoded two block rows per
 * callback; every step of the drawing is split so no callback does much. Then
 * zvis encodes and shows the frame (~30 fps), only while this card is on
 * screen. See ../common/zvis.h. */
#include <stdint.h>
#include "zvis.h"
#include "skull_art.h"

extern unsigned int _Fx_DLY_Skull_Info[];

#define MAGIC 0x534B5534u                      /* 'SKU4' */
#define FXID  416u
#define NOFRAME    0xFFu
#define MAX_SHARDS 160u
#define SHARD_PARTS 16u                        /* callbacks to move and draw the shards */
#define SPARK_PARTS 4u                         /* callbacks to draw the sparks */
#define SNAKE_PARTS 5                          /* callbacks per pass (outline, then body) */
#define BOOM_T     62u                         /* frames of flying, bouncing and lying still */
#define REFORM_T   18u                         /* frames flying home */
#define SPARK_T    24u
#define GRAV       0.32f                       /* px/frame^2 */
#define FLOOR      56.0f                       /* shard top when its bottom row is on the floor */
#define IDLE_WAIT  16538u                      /* ~3 s of callbacks (8 samples at 44.1 kHz) */
#define IDLE_GAP   13782u                      /* ~2.5 s between idle animations */
#define QUIET_LVL  0.06f                       /* below: counts as quiet */
#define WAKE_LVL   0.15f                       /* above: back to the face */
#define DUST_MELT  60u                         /* frames of crumbling, top to bottom */
#define DUST_BACK  100u                        /* re-forming starts */
#define DUST_END   126u

enum { FACE, BOOM, REFORM, SEQ, SNAKE, DUST };

typedef struct {
    float x, y, vx, vy;
    unsigned char spr[8];                      /* white bits, one byte per column */
    unsigned char hx, hy, rot, spin, alive, pad[3];
} Shard;

typedef struct { uint32_t b[2][128], s[2][128], m[2][128]; } Dust;   /* bone, sand, re-form mask; [0] rows 0-31 */

typedef struct {
    unsigned magic, step, shake, flip, tick, mode, t, armed, rest, quiet, idle_k, rng, nshard, dec, have, cur, seq, arg;
    int dx;
    float env, slow, lvl;
    unsigned char img[1024];                   /* the decoded frame */
    union { Shard sh[MAX_SHARDS]; Dust d; } u;
    ZvState z;
} SkullState;

ZV_INLINE(rnd)
static inline uint32_t rnd(SkullState *st)
{
    uint32_t x = st->rng;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    st->rng = x;
    return x;
}

/* One block row from build.py's lz_row format. */
ZV_INLINE(lz_row)
static inline void lz_row(unsigned char *d, const unsigned char *s)
{
    unsigned o = 0;
    while (o < 128u) {
        unsigned t = *s++, n;
        if (t < 0x80u) { n = t + 1u; while (n--) d[o++] = *s++; }
        else {
            unsigned dist = (unsigned)*s++ + 1u;
            n = t - 0x80u + 3u;
            while (n--) { d[o] = d[o - dist]; o++; }
        }
    }
}

/* Decode frame f into img, two block rows per call; 1 when it's all there. */
ZV_INLINE(decode_step)
static inline int decode_step(SkullState *st, unsigned f)
{
    unsigned r;
    if (st->have == f) return 1;
    if (st->dec > 3u) st->dec = 0;             /* never index past img, whatever happened */
    if (st->dec == 0u) st->have = NOFRAME;
    for (r = 2u * st->dec; r < 2u * st->dec + 2u; ++r)
        lz_row(st->img + 128u * r, SKULL_LZ + SKULL_LZOFF[8u * f + r]);
    if (++st->dec < 4u) return 0;
    st->dec = 0; st->have = f;
    return 1;
}

/* Copy img to the screen, shifted right by dx (black comes in). */
ZV_INLINE(copy_shifted)
static inline void copy_shifted(ZvState *z, const unsigned char *src, int dx)
{
    int b, x, lo = dx > 0 ? dx : 0, hi = dx < 0 ? ZV_W + dx : ZV_W;
    for (b = 0; b < 8; ++b) {                  /* plain loops: no test per byte */
        unsigned char *restrict d = &z->frame[b * ZV_W];
        const unsigned char *restrict s = &src[b * ZV_W - dx];
        for (x = 0; x < lo; ++x) d[x] = 0xFFu;
        for (x = lo; x < hi; ++x) d[x] = s[x];
        for (x = hi; x < ZV_W; ++x) d[x] = 0xFFu;
    }
}

/* A diamond of radius r: white (v = 0) or black (v = 1). */
ZV_INLINE(diamond)
static inline void diamond(ZvState *z, int x, int y, int r, int v)
{
    int i;
    for (i = -r; i <= r; ++i) {                /* one vertical span per column, a byte at a time */
        int h = r - (i < 0 ? -i : i), y0 = y - h, y1 = y + h, X = x + i, b;
        if ((unsigned)X >= (unsigned)ZV_W) continue;
        if (y0 < 0) y0 = 0;
        if (y1 > ZV_H - 1) y1 = ZV_H - 1;
        for (b = y0 >> 3; b <= y1 >> 3 && y0 <= y1; ++b) {
            unsigned lo = b == y0 >> 3 ? (unsigned)y0 & 7u : 0u, hi = b == y1 >> 3 ? (unsigned)y1 & 7u : 7u;
            unsigned char m = (unsigned char)((0xFFu << lo) & (0xFFu >> (7u - hi)));
            unsigned char *p = &z->frame[b * ZV_W + X];
            *p = v ? (unsigned char)(*p | m) : (unsigned char)(*p & (unsigned char)~m);
        }
    }
}

ZV_INLINE(sgn)
static inline int sgn(int v) { return v > 0 ? 1 : v < 0 ? -1 : 0; }

/* Snake, parts 0..SNAKE_PARTS-1: black outline of a share of the body each;
 * then as many for the white body; the last also draws the head's eyes and
 * tongue. Head at path index s. */
ZV_INLINE(draw_snake)
static inline void draw_snake(SkullState *st, int s, int tongue, unsigned part)
{
    int share = (SKULL_SNAKE_LEN + SNAKE_PARTS - 1) / SNAKE_PARTS, body = part >= (unsigned)SNAKE_PARTS;
    int p = (int)part - (body ? SNAKE_PARTS : 0), k;
    int k1 = p == SNAKE_PARTS - 1 ? SKULL_SNAKE_LEN : share * (p + 1);
    for (k = share * p; k < k1; ++k) {
        int i = s - k, x, y, r, w;
        if (i < 0) break;
        if (SKULL_PY[i] & 0x80u) continue;     /* inside the skull */
        x = SKULL_PX[i]; y = SKULL_PY[i];
        r = k <= 1 ? 3 : k < SKULL_SNAKE_LEN - 7 ? 2 : k < SKULL_SNAKE_LEN - 3 ? 1 : 0;   /* head, body, tapering tail */
        if (k > 3) {                           /* slither: a travelling sideways wave */
            int a = i > 0 ? i - 1 : 0, b = i + 1 < (int)SKULL_PATH_N ? i + 1 : i;
            int ox = -sgn((int)(SKULL_PY[b] & 63u) - (int)(SKULL_PY[a] & 63u)), oy = sgn((int)SKULL_PX[b] - (int)SKULL_PX[a]);
            w = (int)(signed char)SKULL_COS64[(unsigned)(i * 6 + (int)st->t * 5) & 63u];
            if (w > 60) { x += ox; y += oy; } else if (w < -60) { x -= ox; y -= oy; }
        }
        diamond(&st->z, x, y, body ? r : r + 1, !body);   /* outline black, body white */
        if (body && r == 2 && ((i >> 1) & 3) == 0) diamond(&st->z, x, y, 1, 1);   /* bands */
    }
    if (part == 2u * SNAKE_PARTS - 1u && s >= 3 && !(SKULL_PY[s] & 0x80u)) {
        int x = SKULL_PX[s], y = SKULL_PY[s];
        int hx = sgn(x - (int)SKULL_PX[s - 3]), hy = sgn(y - (int)(SKULL_PY[s - 3] & 63u));
        zv_px(&st->z, x + hx - hy, y + hy + hx, 1); zv_px(&st->z, x + hx + hy, y + hy - hx, 1);   /* eyes */
        if (tongue)
            for (k = 4; k <= 8; ++k) {
                if (k < 8) zv_px(&st->z, x + k * hx, y + k * hy, 0);
                if (k >= 7) { zv_px(&st->z, x + k * hx - hy, y + k * hy + hx, 0); zv_px(&st->z, x + k * hx + hy, y + k * hy - hx, 0); }
            }
    }
}

ZV_INLINE(bitrev8)
static inline unsigned bitrev8(unsigned v)
{
    v = ((v & 0xF0u) >> 4) | ((v & 0x0Fu) << 4);
    v = ((v & 0xCCu) >> 2) | ((v & 0x33u) << 2);
    return ((v & 0xAAu) >> 1) | ((v & 0x55u) << 1);
}

/* Cut shards from 8 cells of cell row cy of the screen, from column cx0:
 * each 8x8 cell is two triangles; those with enough bone fly. */
ZV_INLINE(cut_shards)
static inline void cut_shards(SkullState *st, unsigned cy, unsigned cx0)
{
    unsigned cx, tri, c;
    for (cx = cx0; cx < cx0 + 8u; ++cx) {
        const unsigned char *src = &st->z.frame[cy * 128u + cx * 8u];
        unsigned anti = (cx * 7u + cy * 3u) & 1u;
        for (tri = 0; tri < 2u && st->nshard < MAX_SHARDS; ++tri) {
            Shard *h = &st->u.sh[st->nshard];
            unsigned n = 0;
            for (c = 0; c < 8u; ++c) {
                unsigned m = (0xFFu << (anti ? 7u - c : c)) & 0xFFu, w;
                if (tri) m = ~m & 0xFFu;
                w = ~(unsigned)src[c] & m;
                h->spr[c] = (unsigned char)w;
                while (w) { w &= w - 1u; n++; }
            }
            if (n < 5u) continue;
            h->hx = (unsigned char)(cx * 8u); h->hy = (unsigned char)(cy * 8u);
            h->x = (float)(int)h->hx; h->y = (float)(int)h->hy;
            {   /* outward from the blast, faster the farther out, kicked up */
                uint32_t r = rnd(st);
                float k = 0.11f + (float)(int)(r & 31u) * 0.004f;
                h->vx = ((float)(int)(cx * 8u + (tri ? 2u : 5u)) - (float)SKULL_CX) * k + (float)(int)((r >> 5) & 15u) * 0.12f - 0.9f;
                h->vy = ((float)(int)(cy * 8u + (tri ? 5u : 2u)) - (float)SKULL_CY) * k - 1.5f - (float)(int)((r >> 9) & 15u) * 0.16f;
                h->spin = (r & 0x10000u) ? 1u : 3u;    /* tumbles every 2 or 4 frames */
            }
            h->rot = 0; h->alive = 1;
            st->nshard++;
        }
    }
}

/* Move (BOOM) or bring home (REFORM) and draw shards [a, b), shaken by sx. */
ZV_INLINE(shards)
static inline void shards(SkullState *st, unsigned a, unsigned b, int sx)
{
    unsigned i, c;
    float e = 0.0f;
    if (st->mode == REFORM) {
        float u = (float)(int)st->t * (1.0f / (float)(int)REFORM_T);
        e = u * u * (3.0f - 2.0f * u);
    }
    for (i = a; i < b && i < st->nshard; ++i) {
        Shard *h = &st->u.sh[i];
        int ix, iy, by, sh;
        if (st->mode == REFORM) {              /* vx, vy hold where it lay */
            h->x = h->vx + ((float)(int)h->hx - h->vx) * e;
            h->y = h->vy + ((float)(int)h->hy - h->vy) * e;
            if (e > 0.75f) h->rot = 0;
        } else {
            if (!h->alive) continue;
            h->vy += GRAV; h->x += h->vx; h->y += h->vy;
            if (h->y > FLOOR) {
                h->y = FLOOR;
                if (h->vy > 1.2f) { h->vy = -h->vy * 0.42f; h->vx *= 0.75f; }
                else { h->vy = 0.0f; h->vx *= 0.8f; }
            }
            if (h->x < -9.0f || h->x > 129.0f) { h->alive = 0; continue; }
            if (h->vy != 0.0f && (st->t & h->spin) == 0u) h->rot = (h->rot + 1u) & 3u;
        }
        ix = (int)(h->x + 0.5f) + sx; iy = (int)(h->y + 0.5f);
        if (iy < -7 || iy > 63 || ix < -7 || ix > 127) continue;
        by = iy >> 3; sh = iy - 8 * by;
        {
            unsigned char o[8];
            int mir = h->rot == 1u || h->rot == 2u, c0 = ix < 0 ? -ix : 0, c1 = ix > ZV_W - 8 ? ZV_W - ix : 8, k;
            for (c = 0; c < 8u; ++c) {         /* tumbling: flips */
                unsigned v = h->spr[mir ? 7u - c : c];
                o[c] = (unsigned char)(h->rot >= 2u ? bitrev8(v) : v);
            }
            if (by >= 0) {
                unsigned char *restrict p = &st->z.frame[by * ZV_W + ix];
                for (k = c0; k < c1; ++k) p[k] &= (unsigned char)~(o[k] << sh);
            }
            if (by + 1 < 8 && sh) {
                unsigned char *restrict p = &st->z.frame[(by + 1) * ZV_W + ix];
                for (k = c0; k < c1; ++k) p[k] &= (unsigned char)~(o[k] >> (8 - sh));
            }
        }
    }
}

/* Spark i at frame t of the blast (float pixels). */
ZV_INLINE(spark_at)
static inline void spark_at(unsigned i, float t, float *x, float *y)
{
    float vx = (float)(int)(signed char)SKULL_FVX[i] * (1.0f / 16.0f);
    float vy = (float)(int)(signed char)SKULL_FVY[i] * (1.0f / 16.0f);
    *x = (float)(int)SKULL_FX[i] + vx * t;
    *y = (float)(int)SKULL_FY[i] + vy * t + 0.5f * GRAV * t * t;
}

/* Rows 0..L as two masks (rows 0-31, 32-63). */
ZV_INLINE(rows_to)
static inline void rows_to(int L, uint32_t *m0, uint32_t *m1)
{
    *m0 = L < 0 ? 0u : L >= 31 ? 0xFFFFFFFFu : (2u << L) - 1u;
    *m1 = L < 32 ? 0u : L >= 63 ? 0xFFFFFFFFu : (2u << (L - 32)) - 1u;
}

ZV_INLINE(rotl)
static inline uint32_t rotl(uint32_t v, unsigned k) { return (v << k) | (v >> (32u - k)); }

/* Dust, one column: crumble (melting), fall one row, slide to neighbour n.
 * Two random words a column; the masks are rotations of them (density 1/2
 * per AND). */
ZV_INLINE(dust_col)
static inline void dust_col(SkullState *st, unsigned x, int n, int melt)
{
    Dust *d = &st->u.d;
    uint32_t b0 = d->b[0][x], b1 = d->b[1][x], s0 = d->s[0][x], s1 = d->s[1][x], o0, o1, l0, l1, f0, f1;
    uint32_t r1 = rnd(st), r2 = rnd(st);
    if (melt >= -8) {                          /* crumble rows above the melt line, 1 in 4 a frame */
        uint32_t m0, m1;
        rows_to(melt + ((int)(signed char)SKULL_COS64[(x * 3u) & 63u] >> 5), &m0, &m1);
        m0 &= b0 & r1 & rotl(r2, 11); m1 &= b1 & r2 & rotl(r1, 5);
        b0 &= ~m0; b1 &= ~m1; s0 |= m0; s1 |= m1;
    }
    o0 = b0 | s0; o1 = b1 | s1;                /* fall where the cell below is free */
    l0 = (o0 >> 1) | (o1 << 31); l1 = (o1 >> 1) | 0x80000000u;
    f0 = s0 & ~l0; f1 = s1 & ~l1;
    s0 = (s0 & ~f0) | (f0 << 1);
    s1 = (s1 & ~f1) | (f1 << 1) | (f0 >> 31);
    f1 = (f1 << 1) | (f0 >> 31); f0 <<= 1;     /* where the falling grains are now */
    s0 &= ~(f0 & r1 & r2 & rotl(r1, 7) & rotl(r2, 13));   /* ~1 in 16 dissolves in the air */
    s1 &= ~(f1 & r1 & r2 & rotl(r2, 3) & rotl(r1, 17));
    if (n >= 0 && n < 128) {                   /* blocked: slide down to the side, sometimes;
                                                  falling: drift sideways, sometimes */
        uint32_t q0 = d->b[0][n] | d->s[0][n], q1 = d->b[1][n] | d->s[1][n];
        uint32_t ql0 = (q0 >> 1) | (q1 << 31), ql1 = (q1 >> 1) | 0x80000000u, mv0, mv1;
        o0 = b0 | s0; o1 = b1 | s1;
        l0 = (o0 >> 1) | (o1 << 31); l1 = (o1 >> 1) | 0x80000000u;
        mv0 = s0 & l0 & ~ql0 & ~q0 & rotl(r2, 3);
        mv1 = s1 & l1 & ~ql1 & ~q1 & rotl(r1, 9);
        s0 &= ~mv0; s1 &= ~mv1;
        d->s[0][n] |= mv0 << 1;
        d->s[1][n] |= (mv1 << 1) | (mv0 >> 31);
        mv0 = s0 & f0 & ~q0 & rotl(r1, 23) & rotl(r2, 29);
        mv1 = s1 & f1 & ~q1 & rotl(r2, 15) & rotl(r1, 27);
        s0 &= ~mv0; s1 &= ~mv1;
        d->s[0][n] |= mv0; d->s[1][n] |= mv1;
    }
    d->b[0][x] = b0; d->b[1][x] = b1; d->s[0][x] = s0; d->s[1][x] = s1;
}

#pragma CODE_SECTION(Fx_DLY_Skull, ".audio")
void Fx_DLY_Skull(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    unsigned int *info = _Fx_DLY_Skull_Info;
    uintptr_t base, end;
    SkullState *st;
    unsigned i;
    int visible, on = params[0] >= 0.5f;       /* read first: not after zv_service's loops */
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(SkullState)) return;
    st = (SkullState *)base;
    if (st->magic != MAGIC) {
        st->magic = MAGIC; st->step = 0; st->shake = 0; st->flip = 0; st->tick = 0; st->dx = 0;
        st->mode = FACE; st->t = 0; st->armed = 1; st->rest = 0; st->quiet = 0; st->idle_k = 0;
        st->rng = 0x2545F491u; st->nshard = 0; st->dec = 0; st->have = NOFRAME; st->cur = 0; st->seq = 0; st->arg = 0;
        st->env = 0.0f; st->slow = 0.0f; st->lvl = 0.0f;
        zv_init(&st->z, FXID, info);
        zv_hide_knob_boxes(&st->z, info);      /* full screen (experimental) */
        return;
    }

    visible = zv_visible(&st->z, ctx);
    zv_service(&st->z, info, visible);
    /* Again every callback, not only at start-up: on the pedal the knob boxes
     * came back in v0.04 (filled in after our first callback, or restored on a
     * redraw). Idempotent: it only clears boxes still sized 20x15. */
    zv_hide_knob_boxes(&st->z, info);
    if (!on || !visible) { st->step = 0; st->dec = 0; st->have = NOFRAME; return; }

    {   /* follow the signal every callback */
        float d = zoom_param_norm01(params[6], 0.4f);
        float rel = 0.002f * (1.0f - d) + 0.00002f;
        float sense = zoom_param_norm01(params[5], 0.5f);
        float boom = zoom_param_norm01(params[8], 0.5f);
        float thr = 0.62f * (1.0f - boom) + 0.08f;  /* env needed to explode; boom 0 = never */
        for (i = 0; i < 8u; ++i) {
            float s = (fx[i] + fx[i + 8]) * 0.5f;
            st->env = zv_follow(st->env, s, 0.02f, rel);
            st->slow = zv_follow(st->slow, s, 0.0005f, 0.0005f);
        }
        st->lvl = st->env * (1.0f + sense * sense * 30.0f);
        if (!(st->lvl <= 1.5f)) st->lvl = 1.5f;
        if (st->lvl < QUIET_LVL) { if (st->quiet < 0x7FFFFFFFu) st->quiet++; } else st->quiet = 0;
        if (st->mode >= SEQ && st->lvl > WAKE_LVL) {   /* playing again: the face, now */
            st->mode = FACE; st->step = 0; st->dec = 0; st->have = NOFRAME;
        }
        if (st->mode == FACE && st->env - 1.6f * st->slow > 0.03f && st->shake == 0u)
            st->shake = (unsigned)(int)(zoom_param_norm01(params[7], 0.5f) * 8.0f);   /* frames; 0 = off */
        /* Re-arm only with the face back on screen, the level well down, and
         * ~1 s since it re-formed. */
        if (st->mode == FACE && st->rest < 5512u) st->rest++;
        if (st->mode == FACE && st->rest >= 5512u && st->env < thr * 0.6f) st->armed = 1;
        if (st->mode == FACE && st->armed && boom > 0.004f && st->env > thr && st->step == 0u) {
            st->mode = BOOM; st->t = 0; st->armed = 0; st->shake = 0; st->nshard = 0;
        }
    }
    if (st->z.phase != ZV_IDLE) return;

    if (st->mode == BOOM || st->mode == REFORM) {
        int sx = (st->mode == BOOM && st->t < 14u) ? ((st->t & 1u) ? 1 : -1) * (int)(14u - st->t) / 4 : 0;
        int intro = st->mode == BOOM && st->t < 2u;      /* frame 0: white flash, 1: the negative */
        if (st->mode == BOOM && st->t == 0u && st->step < 16u) {  /* first cut the shards, half a cell row a callback */
            cut_shards(st, st->step >> 1, (st->step & 1u) * 8u); st->step++; return;
        }
        if (st->step == 0u || intro) {
            unsigned char keep = (st->mode == BOOM && st->t == 1u) ? 0xFFu : 0u;
            unsigned char flip = (st->mode == BOOM && st->t == 0u) ? 0u : 0xFFu;
            for (i = 0; i < 1024u; ++i) st->z.frame[i] = (unsigned char)((st->img[i] & keep) ^ flip);
            if (intro) { zv_submit(&st->z); st->step = 0; st->t++; return; }
            if (st->mode == REFORM && st->t == 0u)
                for (i = 0; i < st->nshard; ++i) {
                    Shard *h = &st->u.sh[i];
                    h->vx = h->alive ? h->x : (h->x < 0.0f ? -8.0f : 128.0f);
                    h->vy = h->y;
                }
            st->step = 1;
            return;
        }
        if (st->step <= 2u) {                  /* two shockwaves, one a callback */
            int r = 6 + 9 * ((int)st->t - 2) - 8 * ((int)st->step - 1), a;
            if (st->mode == BOOM && st->t <= 12u && r > 0)
                for (a = 0; a < 64; a += 2) {
                    int x = SKULL_CX + sx + (r * (int)(signed char)SKULL_COS64[a]) / 127;
                    int y = SKULL_CY - (r * (int)(signed char)SKULL_COS64[(a + 48) & 63]) / 178;   /* /127*1.4 */
                    if (y >= 0 && y < ZV_H) zv_px(&st->z, x, y, 0);
                }
            st->step++;
            return;
        }
        if (st->step < 3u + SPARK_PARTS) {     /* sparks, a share a callback */
            if (st->mode == BOOM && st->t < SPARK_T) {
                float t = (float)(int)(st->t - 2u);
                unsigned keep = st->t < 12u ? SKULL_FRAGS : SKULL_FRAGS - (SKULL_FRAGS * (st->t - 12u)) / (SPARK_T - 11u);
                for (i = (st->step - 3u) * (SKULL_FRAGS / SPARK_PARTS); i < (st->step - 2u) * (SKULL_FRAGS / SPARK_PARTS); ++i) {
                    float x, y;
                    if ((i * 37u) % SKULL_FRAGS >= keep) continue;
                    spark_at(i, t, &x, &y);
                    zv_px(&st->z, (int)(x + 0.5f) + sx, (int)(y + 0.5f), 0);
                }
            }
            st->step++;
            return;
        }
        {
            unsigned part = st->step - (3u + SPARK_PARTS), per = MAX_SHARDS / SHARD_PARTS;
            shards(st, part * per, part * per + per, sx);
            if (++st->step < 3u + SPARK_PARTS + SHARD_PARTS) return;
        }
        zv_submit(&st->z);
        st->step = 0;
        if (++st->t >= (st->mode == BOOM ? BOOM_T : REFORM_T)) {
            st->t = 0;
            if (st->mode == BOOM) st->mode = REFORM;
            else { st->mode = FACE; st->armed = 0; st->rest = 0; }
        }
        return;
    }

    if (st->mode == DUST) {
        Dust *d = &st->u.d;
        if (st->step == 0u) {
            if (st->t == 0u)                   /* the face becomes bone bits */
                for (i = 0; i < 128u; ++i) {
                    const unsigned char *f = &st->z.frame[i];
                    d->b[0][i] = ~((uint32_t)f[0] | ((uint32_t)f[128] << 8) | ((uint32_t)f[256] << 16) | ((uint32_t)f[384] << 24));
                    d->b[1][i] = ~((uint32_t)f[512] | ((uint32_t)f[640] << 8) | ((uint32_t)f[768] << 16) | ((uint32_t)f[896] << 24));
                    d->s[0][i] = 0; d->s[1][i] = 0; d->m[0][i] = 0; d->m[1][i] = 0;
                }
            st->step = 1;
            return;
        }
        if (st->step <= 16u) {                 /* two falls a frame, 16 columns a callback */
            unsigned sim = (st->step - 1u) >> 3, chunk = (st->step - 1u) & 7u, k;
            int left = ((st->t * 2u + sim) & 1u) == 0u;
            int melt = (sim == 0u && st->t < DUST_MELT + 20u) ? (int)(st->t * 7u) / 6 - 4 : -100;   /* then the last crumbs */
            for (k = 0; k < 16u; ++k) {
                unsigned x = left ? chunk * 16u + k : 127u - chunk * 16u - k;
                dust_col(st, x, left ? (int)x - 1 : (int)x + 1, melt);
            }
            st->step++;
            return;
        }
        {                                      /* to the screen, 32 columns a callback */
            unsigned x0 = (st->step - 17u) * 32u, x;
            for (x = x0; x < x0 + 32u; ++x) {
                uint32_t o0, o1;
                if (st->t >= DUST_BACK) {      /* re-form: dust thins, the face fills in */
                    const unsigned char *f = &st->img[x];
                    uint32_t r1 = rnd(st), r2 = rnd(st);
                    d->m[0][x] |= r1 & rotl(r2, 7); d->m[1][x] |= r2 & rotl(r1, 13);
                    d->s[0][x] &= r1 | rotl(r2, 19); d->s[1][x] &= r2 | rotl(r1, 25);
                    d->b[0][x] = d->m[0][x] & ~((uint32_t)f[0] | ((uint32_t)f[128] << 8) | ((uint32_t)f[256] << 16) | ((uint32_t)f[384] << 24));
                    d->b[1][x] = d->m[1][x] & ~((uint32_t)f[512] | ((uint32_t)f[640] << 8) | ((uint32_t)f[768] << 16) | ((uint32_t)f[896] << 24));
                }
                o0 = d->b[0][x] | d->s[0][x]; o1 = d->b[1][x] | d->s[1][x];
                st->z.frame[x] = (unsigned char)~o0;          st->z.frame[128u + x] = (unsigned char)~(o0 >> 8);
                st->z.frame[256u + x] = (unsigned char)~(o0 >> 16); st->z.frame[384u + x] = (unsigned char)~(o0 >> 24);
                st->z.frame[512u + x] = (unsigned char)~o1;   st->z.frame[640u + x] = (unsigned char)~(o1 >> 8);
                st->z.frame[768u + x] = (unsigned char)~(o1 >> 16); st->z.frame[896u + x] = (unsigned char)~(o1 >> 24);
            }
            if (++st->step < 21u) return;
        }
        zv_submit(&st->z);
        st->step = 0;
        if (++st->t >= DUST_END) { st->mode = FACE; st->quiet = IDLE_WAIT - IDLE_GAP; }
        return;
    }

    if (st->mode == SEQ || st->mode == SNAKE) {
        if (st->step == 0u) {
            unsigned n = st->mode == SNAKE ? SKULL_SNAKE_N : st->seq == 0u ? SKULL_SEQ_SPIN - SKULL_SEQ_LOOK
                       : st->seq == 1u ? SKULL_SEQ_ROLL - SKULL_SEQ_SPIN : SKULL_SEQ_END - SKULL_SEQ_ROLL;
            if (st->t >= n) { st->mode = FACE; st->quiet = IDLE_WAIT - IDLE_GAP; return; }
            if (st->mode == SNAKE) { st->cur = SKULL_SNAKE[2u * st->t] & 7u; st->arg = SKULL_SNAKE[2u * st->t + 1u] | ((unsigned)(SKULL_SNAKE[2u * st->t] >> 3) << 8); }
            else st->cur = SKULL_SEQ[(st->seq == 0u ? SKULL_SEQ_LOOK : st->seq == 1u ? SKULL_SEQ_SPIN : SKULL_SEQ_ROLL) + st->t];
            st->step = 1;
        }
        if (st->step == 1u) { if (decode_step(st, st->cur)) st->step = 2; return; }
        if (st->step == 2u) { copy_shifted(&st->z, st->img, 0); st->step = 3; if (st->mode == SNAKE) return; }
        if (st->mode == SNAKE && st->step < 3u + 2u * SNAKE_PARTS) {
            draw_snake(st, (int)(st->arg & 0xFFu), (int)(st->arg >> 8), st->step - 3u);
            if (++st->step < 3u + 2u * SNAKE_PARTS) return;
        }
        zv_submit(&st->z);
        st->step = 0; st->t++;
        return;
    }

    /* FACE */
    if (st->step == 0u) {
        int k;
        if (st->quiet >= IDLE_WAIT) {          /* quiet: the next idle animation */
            unsigned a = st->idle_k;
            st->idle_k = a + 1u >= 5u ? 0u : a + 1u;
            st->t = 0; st->quiet = 0;
            if (a == 2u) st->mode = SNAKE;
            else if (a == 4u) st->mode = DUST;
            else { st->mode = SEQ; st->seq = a == 0u ? 0u : a == 1u ? 1u : 2u; }
            return;
        }
        k = (int)(st->lvl * (float)SKULL_JAW_STEPS);
        if (k > (int)SKULL_JAW_STEPS - 1) k = (int)SKULL_JAW_STEPS - 1;
        if (k < 0) k = 0;
        st->cur = (unsigned)k;
        st->dx = 0;
        if (st->shake) { st->flip ^= 1u; st->dx = st->flip ? -2 : 2; st->shake--; }
        st->step = 1;
    }
    if (st->step == 1u) { if (decode_step(st, st->cur)) st->step = 2; return; }
    if (st->step == 2u) { copy_shifted(&st->z, st->img, st->dx); st->step = 3; return; }
    {   /* eye lights, flickering a little with level */
        float lvl = st->lvl;
        int r = lvl > 1.0f ? 3 : lvl > 0.6f ? 2 : lvl > 0.3f ? 1 : lvl > 0.12f ? 0 : -1;
        st->tick++;
        if (r >= 1 && (st->tick & 3u) == 0u) r--;   /* flicker */
        if (r >= 0)
            for (i = 0; i < 2u; ++i)
                diamond(&st->z, (i ? SKULL_EYE_RX : SKULL_EYE_LX) + st->dx, i ? SKULL_EYE_RY : SKULL_EYE_LY, r, 0);
        zv_submit(&st->z);
        st->step = 0;
    }
}
