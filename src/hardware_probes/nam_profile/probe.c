/* NAMProf -- where does the full-rate NAM kernel's time actually go?
 *
 * NAMTime answered "is it over budget" with five coarse buckets (code 5: the
 * kernel averages at or above a whole callback interval). That was enough to
 * explain the crackling, and half/6-8 rate fixed it by doing less work. It is
 * not enough to choose how to make FULL rate fit, because the two candidate
 * fixes attack different costs:
 *
 *   - memory layout / locality, if the kernel is waiting on memory
 *   - 16-bit SIMD arithmetic, if it is genuinely compute-bound
 *
 * The C674x is statically scheduled: with every access hitting L1, a callback
 * costs exactly its emulated cycle count. So REAL minus EMULATED is, to a good
 * approximation, time spent stalled on memory (plus any interrupts). This probe
 * measures the real count; the emulator already gives 18,612 for this kernel.
 *
 * It also reports WHERE the state lives. Read statically from the firmware
 * image (docs/NAM-RUNTIME-INVESTIGATION.md), the boot cache setup is L1D 16 KB,
 * L2 128 KB, and only DDR 0xC0000000-0xC0FFFFFF is marked cacheable. The
 * model's working set is ~140 KB -- just over L2 -- and if the arena sits above
 * 0xC1000000 every access is an uncached DDR round trip. The arena base, its
 * live MAR bit and the live cache config settle which case applies.
 *
 * Register reads are read-only megamodule registers the firmware itself reads
 * (c00d7688); the firmware never configures memory protection, so they are
 * permitted. They happen on the FIRST callback so that if they were somehow
 * not permitted, the failure is immediate and obvious rather than after a
 * minute of silent measuring. Nothing is written to any register, clock or
 * cache setting.
 *
 * REPORTING. Results play as tone bursts: 689 Hz = 0, 1378 Hz = 1, 10 ms each
 * with 5 ms gaps, 32 bits per word MSB first, a 0.5 s gap between frames.
 * Record the pedal's direct output and decode with
 * tools/decode_namprof.py. Words: see PROF_W_* below.
 */
#include <stdint.h>
#include "measured_core.h"

#ifdef HOST_TEST
static unsigned fake_ticks, fake_step, fake_l2cfg, fake_l1dcfg, fake_mar;
static unsigned clock_read(void) { unsigned v = fake_ticks; fake_ticks += fake_step; return v; }
static unsigned reg_l2cfg(void) { return fake_l2cfg; }
static unsigned reg_l1dcfg(void) { return fake_l1dcfg; }
static unsigned mar_read(unsigned a) { (void)a; return fake_mar; }
#else
#include <c6x.h>
#pragma FUNC_ALWAYS_INLINE(clock_read)
static inline unsigned clock_read(void) { return TSCL; }
#pragma FUNC_ALWAYS_INLINE(reg_l2cfg)
static inline unsigned reg_l2cfg(void) { return *(volatile unsigned *)0x01840000u; }
#pragma FUNC_ALWAYS_INLINE(reg_l1dcfg)
static inline unsigned reg_l1dcfg(void) { return *(volatile unsigned *)0x01840040u; }
/* One MAR per 16 MB region: MAR[n] at 0x01848000 + 4n, n = address >> 24. */
#pragma FUNC_ALWAYS_INLINE(mar_read)
static inline unsigned mar_read(unsigned a)
{ return *(volatile unsigned *)(0x01848000u + ((a >> 24) << 2)); }
#endif

#define PROF_MAGIC 0x4e505231u
#define PROF_SYNC  0x5a5aa5a5u
enum {
    PROF_W_SYNC, PROF_W_PERIOD, PROF_W_AVG, PROF_W_PEAK, PROF_W_MIN,
    PROF_W_ARENA_BASE, PROF_W_ARENA_END, PROF_W_ARENA_MAR,
    PROF_W_L1DCFG, PROF_W_L2CFG, PROF_W_WEIGHTS, PROF_W_CTX, PROF_W_FX,
    PROF_W_CHECK, PROF_WORDS
};
#define PROF_TONE 441u      /* 10 ms burst */
#define PROF_SLOT 661u      /* + 5 ms gap  */
#define PROF_GAP  22050u    /* 0.5 s between frames */
#define PROF_N    4096u     /* callbacks measured, a power of two for >>12 */

typedef struct {
    unsigned magic, stage, calls, last, elapsed;
    unsigned total, peak, lo;
    unsigned word, bit, t, gap, phase;
    unsigned w[PROF_WORDS];
} Prof;

#pragma CODE_SECTION(Fx_FLT_NAMProf, ".audio")
void Fx_FLT_NAMProf(uintptr_t *ctx)
{
    unsigned *src = (unsigned *)ctx[12], *dst = *(unsigned **)ctx[11];
    uintptr_t *d = (uintptr_t *)ctx[3];
    float *p = (float *)ctx[1], *fx = (float *)ctx[5];
    unsigned i, now = clock_read();
    uintptr_t base;
    PedalNam *net;
    Prof *m;
    *dst = *src;
    if (!d || !d[0] || d[1] <= d[0] || d[1] - d[0] < 8u) return;
    base = (d[0] + 7u) & ~(uintptr_t)7u;
    if (d[1] - base < sizeof(PedalNam) + sizeof(Prof)) return;
    net = (PedalNam *)base;
    m = (Prof *)(base + sizeof(PedalNam));
    if (p[0] < 0.5f) { m->magic = 0; return; }

    if (m->magic != PROF_MAGIC) {
        m->magic = PROF_MAGIC; m->stage = 0; m->calls = 0; m->last = now;
        m->elapsed = 0; m->total = 0; m->peak = 0; m->lo = 0xffffffffu;
        m->word = 0; m->bit = 0; m->t = 0; m->gap = PROF_GAP; m->phase = 0;
        for (i = 0; i < (unsigned)PROF_WORDS; ++i) m->w[i] = 0;
        m->w[PROF_W_SYNC]       = PROF_SYNC;
        m->w[PROF_W_ARENA_BASE] = (unsigned)d[0];
        m->w[PROF_W_ARENA_END]  = (unsigned)d[1];
        m->w[PROF_W_ARENA_MAR]  = mar_read((unsigned)d[0]);   /* first callback: fail fast */
        m->w[PROF_W_L1DCFG]     = reg_l1dcfg();
        m->w[PROF_W_L2CFG]      = reg_l2cfg();
        m->w[PROF_W_WEIGHTS]    = (unsigned)(uintptr_t)nam_weights;
        m->w[PROF_W_CTX]        = (unsigned)(uintptr_t)ctx;
        m->w[PROF_W_FX]         = (unsigned)(uintptr_t)fx;
        net->magic = 0;
        return;
    }

    if (m->stage == 0) {             /* callback interval, dry through untouched */
        m->elapsed += now - m->last; m->last = now;
        if (++m->calls == PROF_N) {
            m->w[PROF_W_PERIOD] = m->elapsed >> 12;
            m->calls = 0; m->stage = 1;
        }
        return;
    }

    /* Stages 1 (warm) and 2 (measure) share ONE call site. Two calls would make
     * the compiler inline the whole kernel twice -- measured: 12.6 KB of .audio
     * instead of ~6.8 KB and six extra relocation pairs -- a needless departure
     * from NAMTime's hardware-proven layout. Warm-up is timed and discarded. */
    if (m->stage == 1 || m->stage == 2) {
        unsigned start = clock_read(), cost;
        nam_core(ctx);
        cost = clock_read() - start;
        if (m->stage == 1) {
            if (net->ready && net->warm >= 8192u) { m->stage = 2; m->calls = 0; }
            return;
        }
        m->total = cost > 0xffffffffu - m->total ? 0xffffffffu : m->total + cost;
        if (cost > m->peak) m->peak = cost;
        if (cost < m->lo) m->lo = cost;
        if (++m->calls == PROF_N) {
            m->w[PROF_W_AVG]  = m->total >> 12;
            m->w[PROF_W_PEAK] = m->peak;
            m->w[PROF_W_MIN]  = m->lo;
            m->w[PROF_W_CHECK] = 0;
            for (i = 1; i < (unsigned)PROF_W_CHECK; ++i) m->w[PROF_W_CHECK] ^= m->w[i];
            m->stage = 3;
        }
        return;
    }

    /* stage 3: the network is parked; play the report, no dry signal */
    for (i = 0; i < 8u; ++i) {
        float out = 0.0f;
        if (m->gap) {
            --m->gap;
        } else {
            unsigned bit = (m->w[m->word] >> (31u - m->bit)) & 1u;
            if (m->t < PROF_TONE) {
                unsigned ph = m->phase;
                float v = (ph < 32u ? (float)ph : (float)(64u - ph)) * (1.0f / 16.0f) - 1.0f;
                out = 0.12f * v;
                m->phase = (ph + (bit ? 2u : 1u)) & 63u;
            } else {
                m->phase = 0;        /* every burst starts at the same point */
            }
            if (++m->t == PROF_SLOT) {
                m->t = 0;
                if (++m->bit == 32u) {
                    m->bit = 0;
                    if (++m->word == (unsigned)PROF_WORDS) { m->word = 0; m->gap = PROF_GAP; }
                }
            }
        }
        fx[i] = out; fx[i + 8] = out;
    }
}

#ifdef HOST_TEST
unsigned prof_bytes(void) { return sizeof(PedalNam) + sizeof(Prof); }
unsigned net_bytes(void) { return sizeof(PedalNam); }
void set_clock(unsigned v) { fake_ticks = v; }
void set_step(unsigned v) { fake_step = v; }
void set_regs(unsigned l2, unsigned l1d, unsigned mar) { fake_l2cfg = l2; fake_l1dcfg = l1d; fake_mar = mar; }
#endif
