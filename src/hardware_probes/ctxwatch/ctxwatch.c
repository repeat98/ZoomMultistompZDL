/*
 * ctxwatch.c -- which ctx[] region reacts to a SysEx patch write?
 *
 * THE QUESTION
 * The MS-70CDR honours live 0x31 param edits only on slots 1-3. On slots 4-6
 * a 0x28 patch write updates the stored patch (a read-back proves it) but the
 * running effect never hears it: params[] is not refreshed, so a custom effect
 * keeps playing the old values until the slot is re-instantiated. The pedal's
 * OWN encoder does update those slots, so the firmware has a working path --
 * SysEx just does not reach it.
 *
 * If some OTHER host-owned region does track the write, a custom effect could
 * read its knob values from there instead of params[] and behave identically
 * on all six slots, with no bypass bounce and no audible gap. This probe looks
 * for that region.
 *
 * HOW IT REPORTS
 * Every block it hashes a window of memory behind each watched ctx word and
 * compares with the previous hash. When one changes it emits that word's index
 * as a burst of short blips: 3 blips = ctx[3]. One test tells you which region
 * moved, instead of sixteen separate listens.
 *
 * The known audio buffers (ctx[4], [5], [6], [12], [13], [14]) are skipped --
 * they change every block by definition and would blip continuously. ctx[1] is
 * watched deliberately as the CONTROL: it is the params table, and the whole
 * point is that it should NOT react on slots 4-6.
 *
 * HOW TO USE
 *   1. Back up your patches first (Patch Editor -> Backup bank).
 *   2. Load CtxWatch into slot 4 of a patch and switch it on.
 *   3. Let it settle -- it should be silent.
 *   4. From the Patch Editor, change one of ITS knobs and hit Apply.
 *   5. Count the blips. That is the ctx index whose region tracked the write.
 *      Silence everywhere means nothing visible to the DSP changed, and the
 *      bypass bounce stays the only route.
 *
 * Knobs:
 *   Span/Level knobs exist in the manifest but are IGNORED by the DSP --
 *   see the note at the constants below.
 *
 * SAFETY
 * Dereferencing a ctx word that is not a pointer is exactly how you hard-freeze
 * this DSP, so every candidate is filtered first: non-zero, 4-byte aligned, and
 * inside the address window the host arena actually occupies. A word failing
 * the filter is skipped silently rather than read. `ctxmap` never dereferenced
 * at all; this one does, deliberately and behind a guard -- if the pedal does
 * lock up, a rewrite from Effect Manager clears it.
 *
 * Safe-DSP: no math lib, no runtime divide, no modulo, no switch, no static
 * arrays, no float->unsigned casts. State lives in the ctx[3] arena.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "ctxwatch_params.h"

#ifndef CTXWATCH_AUDIO_FUNC
#define CTXWATCH_AUDIO_FUNC Fx_SFX_CtxWatch
#endif

#define CTXWATCH_DO_PRAGMA(x) _Pragma(#x)
#define CTXWATCH_EXPAND_PRAGMA(x) CTXWATCH_DO_PRAGMA(x)
#define CTXWATCH_CODE_SECTION(f) CTXWATCH_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

CTXWATCH_CODE_SECTION(CTXWATCH_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define CW_MAGIC   0x43575443u   /* 'CWTC' */
#define CW_VERSION 1u

#define CW_SLOTS      16
#define CW_ADDR_LO    0x80000000u   /* the window the host arena lives in */
#define CW_ADDR_HI    0x90000000u
/* 150 ms on / 150 ms off. At the old 1800 samples (41 ms) blips fired ~24 times
 * a second -- impossible to COUNT, which is the one thing they exist for, and
 * indistinguishable from the alive-hum's wobble. */
#define CW_BLIP_ON    8820          /* 200 ms -- countable */
#define CW_BLIP_OFF   8820
#define CW_LEAD       66150         /* 1.5 s of silence before a burst, so the
                                     * count is clearly delimited from anything
                                     * that came before it */
#define CW_CHIRP      8820          /* boot beep length */
#define CW_SETTLE     220500        /* 5 s: absorb start-up churn SILENTLY */
#define CW_STABLE_MIN 1500          /* ~0.27 s of stillness before a change counts */

typedef struct CtxWatchState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t settle;
    uint32_t hash[CW_SLOTS];
    int32_t  blipsLeft;             /* blips still to emit */
    int32_t  blipPhase;             /* position inside the current blip */
    uint32_t tone;
    int32_t  watched;               /* regions that passed the pointer guard */
    uint32_t stable[CW_SLOTS];      /* blocks each region has held still */
    uint32_t reported;              /* bitmask: an index reports ONCE, ever */
    int32_t  lead;                  /* silent run-up before a burst */
    int32_t  chirp;                 /* boot beep countdown */
    uint32_t chirpTone;             /* pitch selector for the boot beep */
    uint32_t booted;
} CtxWatchState;

/* Words that change every block by definition. The audio buffers were obvious;
 * ctx[3] and ctx[11] were not, and both made the probe beep continuously:
 * ctx[3] is the arena THIS PROBE's own state lives in (it rewrites tone and
 * blipPhase every block), and ctx[11] is the magic-shuttle destination we write
 * through every block. A probe must not watch memory it is itself churning. */
static inline int cw_skip(int i)
{
    return (i == 3 || i == 4 || i == 5 || i == 6 ||
            i == 11 || i == 12 || i == 13 || i == 14);
}

/* Fallback hum for the early-return paths, so a bail-out is still audible.
 * STATELESS on purpose: a `static` counter here put 4 bytes in .fardata and
 * pulled in 2 relocations, which is a documented freeze class on this DSP. The
 * phase comes from the sample index instead -- 4 up, 4 down is ~5.5 kHz, plenty
 * audible and needs no storage. */
static inline void cw_hum(float *fx, float *out, float amp)
{
    int i;
    for (i = 0; i < 8; i++) {
        float v = (i < 4) ? amp : -amp;
        fx[i] += v; fx[i + 8] += v;
        out[i] += v; out[i + 8] += v;
    }
}

/* The guard window is derived from pointers the firmware ALREADY hands us and we
 * already dereference safely (params, the audio buffers, the arena). A hardcoded
 * range was a guess that could reject the very region we are hunting; this bounds
 * the search by observed-good addresses instead. */
static inline int cw_safe(uint32_t v, uint32_t lo, uint32_t hi)
{
    if (v == 0u) return 0;
    if (v & 3u) return 0;                       /* must be 4-byte aligned */
    if (v < lo || v >= hi) return 0;
    return 1;
}

void CTXWATCH_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);
    float *outBuf = ZDL_PTR(float *, ctx[6]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    /* Deliberately NOT gated on params[0]. On slots 4-6 params[] is exactly what
     * fails to update, so gating on it lets the bug under investigation silence
     * the instrument measuring it -- which is what the first two runs hit. A
     * probe should ignore bypass and always report. */

    /* Emit the alive-hum FIRST, before any guard can bail out. Steady hum = the
     * audio function is running; hum with a slow wobble = it is also watching at
     * least one region. Silence now means only one thing: not being called. */
    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) { cw_hum(fxBuf, outBuf, 0.05f); return; }
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    if (base == 0u || end <= base) { cw_hum(fxBuf, outBuf, 0.05f); return; }
    if ((base & 3u) != 0u)          { cw_hum(fxBuf, outBuf, 0.05f); return; }
    if (base + sizeof(CtxWatchState) > end) { cw_hum(fxBuf, outBuf, 0.05f); return; }

    CtxWatchState *st = (CtxWatchState *)base;

    if (st->magic != CW_MAGIC || st->version != CW_VERSION || !st->initialized) {
        st->magic = CW_MAGIC;
        st->version = CW_VERSION;
        st->settle = CW_SETTLE;
        st->blipsLeft = 0;
        st->blipPhase = 0;
        st->tone = 0u;
        st->watched = 0;
        int k;
        for (k = 0; k < CW_SLOTS; k++) { st->hash[k] = 0u; st->stable[k] = 0u; }
        st->reported = 0u; st->lead = 0; st->chirp = 0;
        st->chirpTone = 0u; st->booted = 0u;
        st->initialized = 1u;
    }

    /* Deliberately NOT read from params[]. On slot 4 the Patch Editor writes
     * this effect's params as zeros, so a knob-derived amplitude silenced the
     * probe -- and knobs are the exact thing under investigation. A probe must
     * not depend on the mechanism it is testing. Both values are now fixed. */
    float span = 0.4f;
    int32_t nWords = 8 + (int32_t)(span * 248.0f);      /* 8 .. 256 words */

    /* Re-hash every watched region and note the FIRST that moved. Only look
     * once we are past the settle window, so start-up churn is not reported. */
    /* Scan EVERY block, including during settle, so hashes are primed and
     * `watched` is known before the boot beep. Only REPORTING is gated. */
    {
        /* window: min/max of known-good pointers, widened by 16 MB each way */
        uint32_t lo = (uint32_t)(uintptr_t)params, hi = lo;
        uint32_t known[5];
        known[0] = (uint32_t)ctx[1];  known[1] = (uint32_t)ctx[3];
        known[2] = (uint32_t)ctx[5];  known[3] = (uint32_t)ctx[6];
        known[4] = (uint32_t)base;
        int kk;
        for (kk = 0; kk < 5; kk++) {
            uint32_t kv = known[kk];
            if (kv == 0u) continue;
            if (kv < lo) lo = kv;
            if (kv > hi) hi = kv;
        }
        lo = (lo > 0x01000000u) ? (lo - 0x01000000u) : 0u;
        hi = hi + 0x01000000u;

        /* Armed only once settled and with nothing already sounding. */
        int armed = (st->settle == 0u && st->chirp <= 0 &&
                     st->lead <= 0 && st->blipsLeft <= 0);

        int i;
        int nWatched = 0;
        for (i = 0; i < CW_SLOTS; i++) {
            if (cw_skip(i)) continue;
            uint32_t p = (uint32_t)ctx[i];
            if (!cw_safe(p, lo, hi)) continue;
            nWatched++;
            const volatile uint32_t *m = (const volatile uint32_t *)(uintptr_t)p;
            uint32_t h = 2166136261u;                   /* FNV-ish, cheap */
            int32_t w;
            for (w = 0; w < nWords; w++) {
                h ^= m[w];
                h *= 16777619u;
            }
            if (st->hash[i] == h) {
                if (st->stable[i] < 0xFFFFFFFFu) st->stable[i]++;
            } else {
                uint32_t was = st->hash[i];
                uint32_t held = st->stable[i];
                uint32_t bit = 1u << i;
                st->hash[i] = h;
                st->stable[i] = 0u;
                /* ONE report per index, ever. A region that churns burns its
                 * single report off in the first seconds and is then silent
                 * forever -- which is why the old build made "the same sound
                 * regardless": every change re-blipped, endlessly. With the
                 * latch, a burst is always a discrete event you can count. */
                if (armed && was != 0u && held > CW_STABLE_MIN &&
                    (st->reported & bit) == 0u) {
                    st->reported |= bit;
                    st->blipsLeft = (i == 0) ? 16 : i;  /* ctx[0] -> 16 blips */
                    st->blipPhase = CW_BLIP_ON + CW_BLIP_OFF;
                    st->lead = CW_LEAD;
                    break;
                }
            }
        }
        st->watched = nWatched;

        if (st->settle > 0u) {
            st->settle = (st->settle > 8u) ? (st->settle - 8u) : 0u;
            if (st->settle == 0u && !st->booted) {
                /* Boot beep. Two short HIGH beeps = alive and watching at least
                 * one region; one long LOW buzz = alive but every pointer was
                 * rejected by the guard. Distinguishing those two was the whole
                 * reason the old build needed a permanent carrier hum. */
                st->booted = 1u;
                st->chirp = (nWatched > 0) ? (CW_CHIRP * 3) : (CW_CHIRP * 2);
                st->chirpTone = (nWatched > 0) ? 16u : 128u;
            }
        }
    }

    /* SILENT unless it has something to say. The previous build ran a
     * permanent carrier hum so that silence would not be ambiguous -- but the
     * carrier plus endlessly-repeating blips is exactly why it "kept making the
     * same sound regardless". The boot beep replaces the carrier: it proves the
     * probe is alive once, up front, and then everything goes quiet. After that,
     * ANY sound is a detection. */
    float amp = 0.12f;
    uint32_t tone  = st->tone;
    int32_t blips  = st->blipsLeft;
    int32_t phase  = st->blipPhase;
    int32_t lead   = st->lead;
    int32_t chirp  = st->chirp;
    uint32_t ctone = st->chirpTone;

    int i2;
    for (i2 = 0; i2 < 8; i2++) {
        tone++;
        float v = 0.0f;
        if (chirp > 0) {
            /* high: beep-gap-beep. low: one continuous buzz. */
            int on = (ctone == 16u)
                   ? ((chirp > (CW_CHIRP * 2)) || (chirp <= CW_CHIRP))
                   : 1;
            if (on) v = (tone & ctone) ? amp : -amp;
            chirp--;
        } else if (lead > 0) {
            lead--;                                  /* deliberate silence */
        } else if (blips > 0) {
            if (phase > CW_BLIP_OFF) v = (tone & 32u) ? amp : -amp;
            phase--;
            if (phase <= 0) {
                blips--;
                phase = (blips > 0) ? (CW_BLIP_ON + CW_BLIP_OFF) : 0;
            }
        }
        fxBuf[i2] += v;
        fxBuf[i2 + 8] += v;
        outBuf[i2] += v;
        outBuf[i2 + 8] += v;
    }

    st->lead = lead;
    st->chirp = chirp;
    st->tone = tone;
    st->blipsLeft = blips;
    st->blipPhase = phase;
}
