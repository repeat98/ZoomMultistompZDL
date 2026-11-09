/*
 * dustbox.c -- Dustbox: DOD FX33 Buzz Box clone, MS-70CDR (vacuum-cleaner
 * theme naming -- no DOD/FX33/Buzz branding).
 *
 * Pedal port of tools/audio_preview/renderers/dustbox.py. 4 knobs, left to
 * right matching the real FX33's panel order:
 *   Dust   (params[5]) - (was Heavy) blend distortion <-> sub-octave fuzz
 *                        (the ONLY knob that adds the 2-octaves-down
 *                        effect; at 0 the octave branch is fully absent)
 *   Motor  (params[6]) - (was Buzz) Grunge distortion gain / amount
 *                        (distortion ONLY, never introduces the octave
 *                        branch into the mix)
 *   Filter (params[7]) - (was Saw) tone: single high-shelf, Grunge branch
 *                        ONLY (see DB_HIGH_SHELF_*; never touches the
 *                        octave branch)
 *   Power  (params[8]) - (was Thrust) output level
 *
 * Two branches, like the original (Grunge -> Blue Box generation, then
 * parallel to the blend):
 *   [A] Grunge: pre high-pass -> gain -> asymmetric cubic soft-clip ->
 *       interstage low-pass -> second soft-clip -> Filter high-shelf.
 *   [B] Blue Box octave: fed by [A]'s DISTORTED (pre-tone) output (matching
 *       the real circuit -- Grunge feeds Blue Box), envelope follower + a
 *       loose comparator-input low-pass (not a clean pitch tracker) ->
 *       zero-crossing detector with fixed hysteresis -> /4 flip-flop
 *       divider (two software biquad-free biestables, exactly the CD4013
 *       trick) -> square gated by the envelope -> fuzz clip -> anti-alias
 *       low-pass. Runs parallel to (bypasses) the Filter tone stage: real
 *       circuit sums the octave in after the Grunge's own tone control, not
 *       through it, so Filter never colors the octave's bass.
 *       Feeding the divider harmonics instead of a clean tone is
 *       deliberate: it free-runs somewhere near-but-not-exactly two octaves
 *       down and gets progressively more unstable as Motor (gain) rises --
 *       the real circuit's "extreme/random" chainsaw chaos, not a clean
 *       tracked sub-octave. Coefficients tuned against tools/audio_preview/
 *       renderers/dustbox.py's divide-rate instrumentation harness.
 * mix = Filter(A)*(1-Dust) + B*Dust; then Power + clamp.
 *
 * Safe-DSP: no math lib (cubic soft-clip, one-pole filters with literal
 * coefficients, flip-flop octave instead of pitch tracking), no runtime
 * divide, no static arrays, no big buffer. Tiny persistent state in the
 * ctx[3] arena. ctx[11]/ctx[12] magic shuttle preserved.
 */

#include <stdint.h>

#include "../../airwindows/common/zoom_params.h"
#include "dustbox_params.h"

#ifndef DUSTBOX_AUDIO_FUNC
#define DUSTBOX_AUDIO_FUNC Fx_DLY_Dustbox
#endif

#define DB_DO_PRAGMA(x) _Pragma(#x)
#define DB_EXPAND_PRAGMA(x) DB_DO_PRAGMA(x)
#define DB_CODE_SECTION(f) DB_EXPAND_PRAGMA(CODE_SECTION(f, ".audio"))

DB_CODE_SECTION(DUSTBOX_AUDIO_FUNC)

#define ZDL_PTR(type, word) ((type)(uintptr_t)(word))

#define DB_MAGIC   0x44535442u   /* 'DSTB' */
#define DB_VERSION 1u

/* One-pole coefficients baked for SR = 44100 (compile to immediates). */
#define DB_HP_COEF        0.013f     /* pre high-pass ~90 Hz */
#define DB_LP_INTER_COEF  0.575f     /* interstage low-pass ~6 kHz */
#define DB_PITCH_LP_COEF  0.015f     /* comparator input low-pass ~105 Hz */
#define DB_OCT_LP_COEF    0.35f      /* octave anti-alias low-pass ~2.8 kHz */
#define DB_ENV_ATK        0.97757f   /* env attack ~1 ms */
#define DB_ENV_REL        0.99955f   /* env release ~50 ms */
#define DB_BIAS           0.12f      /* asymmetry bias */
#define DB_GATE_THR       0.004f     /* octave gate threshold */
#define DB_HYST_BASE      0.02f      /* comparator hysteresis (fixed, not envelope-scaled) */

/* Filter (real panel label "SAW (HIGH)") tone control, per the REAL FX33
 * schematic (081182A5, traced from the actual PCB by the user): a SINGLE
 * op-amp stage (U2A) with the tone pot (P2) in its network -- NOT a
 * two-band tilt an earlier pass guessed at (that guess cited a different
 * pedal's schematic, "FX69 Grunge", which was never actually seen --
 * extrapolation, not evidence). A two-band tilt needs two independent
 * op-amps; the real FX33 only has one (U2A) for this control, and the
 * panel silkscreen literally says "SAW (HIGH)" -- a single high-shelf, not
 * a low/high seesaw. Corner estimated from R51 (2K) + C24 (8.2nF) and R49
 * (22K) + C24 in the feedback/input network -- roughly 900 Hz to 10 kHz
 * depending which resistor dominates -- but the full network (R48/R50/R52,
 * C23 50pF too) can't be fully resolved from a schematic photo alone;
 * DB_HIGH_SHELF_COEF/DEPTH are an ear-tuned estimate. */
#define DB_HIGH_SHELF_COEF  0.34755f  /* ~3 kHz corner (highs = signal - lowpass) */
#define DB_HIGH_SHELF_DEPTH 1.1f      /* Filter=0 -> darker than flat; Filter=1 -> brighter */

/* Real FX33 schematic (081182A5, traced from the actual PCB by the user):
 * the FIRST gain stage (U1A, a 4558) has NO pot anywhere in its feedback
 * network (R7 100K in, R12 220K feedback, plus a transistor -- Q5 -- sitting
 * IN the feedback loop with R9/R10/R11/C6/C7, a classic "transistor in the
 * feedback path" soft-limiter that adds gain AND its own saturation beyond
 * the plain R12/R7 ratio). This stage is completely independent of any pot
 * -- it is always driving the signal hard. Only the SECOND stage (U1B) has
 * a pot in its feedback network: P3, labelled "BUZZ (DISTORTION)" on the
 * schematic (Motor knob here), feeding diode clippers (D2/D3) at its
 * output.
 *
 * So DB_DRIVE_FIXED is a plain constant -- Motor only moves stage2. The
 * R12/R7 ratio alone is a modest ~2.2x, but that ignores Q5's added
 * nonlinear gain, which isn't a simple resistor ratio and can't be read off
 * the schematic photo precisely -- DB_DRIVE_FIXED is an ear-tuned estimate
 * of "the whole U1A stage", not a literal component-value calculation. If
 * minimum Motor still isn't hot enough on hardware, raise this first (it's
 * the whole story of "not clean at 0"). */
#define DB_DRIVE_FIXED    16.0f
/* U1B/P3 is a standard non-inverting gain-with-pot stage: feedback = R16
 * (10K, always in circuit) + P3 (0..100K), against R17 (470R, C11 10uF is
 * ~0 ohms at audio so it doesn't add impedance) to ground. That is
 * Av = 1 + (R16+P3)/R17 = ~22x at Motor=0 up to ~235x at Motor=100 -- far
 * more than the old 2..12 range here, which under-drove Motor across its
 * whole travel. Not scaled 1:1 into this range (ilp is already soft-clipped
 * into roughly [-1,1] by the time STAGE2 multiplies it, so anything past
 * ~10x already means "fully saturated" in a normalized float domain -- a
 * literal 235x would make the knob feel like an on/off switch). Widened
 * instead to keep the same ~10x min->max span as the real pot while landing
 * both ends much hotter. */
#define DB_STAGE2_MIN     8.0f
#define DB_STAGE2_SPAN    40.0f

/*
 * DB_PITCH_LP_COEF/DB_HYST_BASE tuned empirically (see dustbox.py's
 * divide-rate instrumentation harness) across E2/A2/G3/E4 test notes and
 * Motor (gain) 0..100: this pair never goes silent on any note/gain combo,
 * tracks a recognizably low, mostly-stable sub-octave at low Motor, and
 * gets progressively more unstable/higher-jumping as Motor rises -- i.e.
 * Motor (the distortion gain) also controls how chaotic the octave divider
 * is, since the divider is fed by the distorted signal. Dust only controls
 * how much of that octave makes it into the final mix.
 */

typedef struct DustboxState {
    uint32_t magic;
    uint32_t version;
    uint32_t initialized;
    uint32_t pad;

    float hp, ilp;       /* distortion filters */
    float env;           /* envelope follower */
    float plp;           /* pitch low-pass */
    float olp;            /* octave low-pass */
    float hiLP;           /* Filter high-shelf: low-pass state (highs = a - hiLP) */
    int32_t sign;        /* zero-crossing state */
    int32_t ff1, ff2;    /* /4 flip-flop divider */

    /* Edit-driven knob latch. The host clobbers the whole param block on
     * patch load AND when refocusing the effect in the chain UI (all slots
     * change at once, sometimes to garbage). A real knob turn changes ONE
     * slot at a time. So: accept a slot's value only when it is the lone
     * change since the last block; otherwise hold the last accepted value.
     * This also fixes turning Dust to 0: zoom_param_norm01() alone can't
     * tell "genuine zero" apart from "uninitialized" and was falling back
     * to the 0.5 default, so full-distortion (Dust=0) still had octave
     * blended in. */
    float accKnob[4];    /* accepted Dust/Motor/Filter/Power (norm) */
    float prevRaw[4];    /* raw slot values last block */
} DustboxState;

static inline float db_soft(float x)
{
    if (x > 1.0f) return 1.0f;
    if (x < -1.0f) return -1.0f;
    return 1.5f * x - 0.5f * x * x * x;
}

void DUSTBOX_AUDIO_FUNC(unsigned int *ctx)
{
    float *params = ZDL_PTR(float *, ctx[1]);
    float *fxBuf  = ZDL_PTR(float *, ctx[5]);

    unsigned int *magicSrc = ZDL_PTR(unsigned int *, ctx[12]);
    unsigned int *magicDst = ZDL_PTR(unsigned int *, *(unsigned int *)ZDL_PTR(unsigned int *, ctx[11]));
    *magicDst = *magicSrc;

    if (params[0] < 0.5f) return;

    volatile unsigned int *desc = ZDL_PTR(volatile unsigned int *, ctx[3]);
    if (!desc) return;
    uintptr_t base = (uintptr_t)desc[0];
    uintptr_t end  = (uintptr_t)desc[1];
    unsigned int span = desc[2];
    if (base == 0u || end <= base) return;
    if ((base & 3u) != 0u || (end & 3u) != 0u || (span & 3u) != 0u) return;
    /* Cross-check the host's own claimed span against end-base -- see
     * uroboros.c/shatter.c: an untrustworthy `end` (transiently
     * inconsistent, e.g. mid patch-switch) let shatter.c's ring-clear
     * write a real heap-buffer-overflow, ASan-confirmed 2026-08-10 and
     * traced to a hardware freeze on rapid patch switching. Ported here
     * as the same class of gap, not independently reproduced on this
     * file. */
    uintptr_t bytes = end - base;
    if (span < bytes) return;
    if (bytes < (uintptr_t)sizeof(DustboxState)) return;

    DustboxState *st = (DustboxState *)base;
    if (st->magic != DB_MAGIC || st->version != DB_VERSION || !st->initialized) {
        st->magic = DB_MAGIC;
        st->version = DB_VERSION;
        st->hp = st->ilp = 0.0f;
        st->env = 0.0f;
        st->plp = st->olp = 0.0f;
        st->hiLP = 0.0f;
        st->sign = 0;
        st->ff1 = st->ff2 = 0;
        st->accKnob[0] = zoom_param_norm01(params[DUSTBOX_DUST_SLOT], DUSTBOX_DUST_DEFAULT_NORM);
        st->accKnob[1] = zoom_param_norm01(params[DUSTBOX_MOTOR_SLOT], DUSTBOX_MOTOR_DEFAULT_NORM);
        st->accKnob[2] = zoom_param_norm01(params[DUSTBOX_FILTER_SLOT], DUSTBOX_FILTER_DEFAULT_NORM);
        st->accKnob[3] = zoom_param_norm01(params[DUSTBOX_POWER_SLOT], DUSTBOX_POWER_DEFAULT_NORM);
        st->prevRaw[0] = st->prevRaw[1] = st->prevRaw[2] = st->prevRaw[3] = -1.0f;
        st->initialized = 1u;
    }

    /* See DustboxState.accKnob comment: only a lone single-slot change is
     * treated as a real knob turn (and a raw <= 0.0001 turn is accepted as
     * true zero); bulk param-block rewrites hold the last accepted values. */
    {
        float raw[4];
        int k, changed = -1, nch = 0;
        raw[0] = params[DUSTBOX_DUST_SLOT];
        raw[1] = params[DUSTBOX_MOTOR_SLOT];
        raw[2] = params[DUSTBOX_FILTER_SLOT];
        raw[3] = params[DUSTBOX_POWER_SLOT];
        for (k = 0; k < 4; k++) {
            float d = raw[k] - st->prevRaw[k];
            if (d > 1.0e-6f || d < -1.0e-6f) { changed = k; nch++; }
            st->prevRaw[k] = raw[k];
        }
        if (nch == 1) {
            float v = raw[changed];
            float n = zoom_param_norm01(v, st->accKnob[changed]);
            st->accKnob[changed] = n;
        }
    }

    float dust   = st->accKnob[0];
    float motor  = st->accKnob[1];
    float filter = st->accKnob[2];
    float power  = st->accKnob[3];

    float drive     = DB_DRIVE_FIXED;                         /* U1A: fixed, no pot */
    float stage2    = DB_STAGE2_MIN + motor * DB_STAGE2_SPAN;  /* U1B/P3: the actual Motor pot */
    float shelf     = (filter - 0.5f) * 2.0f * DB_HIGH_SHELF_DEPTH;  /* -depth..+depth */
    /* Traced downstream to the real output stage: Thrust/Power (P1) feeds a
     * plain emitter-follower buffer (Q9) -- unity gain, no attenuation built
     * in at max. The old `* 0.7f` ceiling had no basis in the schematic and
     * permanently capped loudness ~3 dB below full scale at any setting;
     * Power now runs the full 0..1 range, with the existing +/-1 clamp
     * below as the safety net. */
    float outGain   = power;
    float biasOut   = db_soft(DB_BIAS);

    float hp = st->hp, ilp = st->ilp;
    float env = st->env, plp = st->plp, olp = st->olp;
    float hiLP = st->hiLP;
    int sign = st->sign, ff1 = st->ff1, ff2 = st->ff2;

    int i;
    for (i = 0; i < 8; i++) {
        float in = 0.5f * (fxBuf[i] + fxBuf[i + 8]);

        /* pre high-pass */
        hp += DB_HP_COEF * (in - hp);
        float xin = in - hp;

        /* [A] Grunge distortion branch */
        float a = db_soft(xin * drive + DB_BIAS) - biasOut;
        ilp += DB_LP_INTER_COEF * (a - ilp);
        a = db_soft(ilp * stage2);

        /* [B] Blue Box octave branch, fed by the DISTORTED signal `a` (not
         * clean `xin`): real-circuit topology, and the harmonics are what
         * make the divider chaotic instead of a clean synth octave. */
        float v = a >= 0.0f ? a : -a;
        float ecoef = (v > env) ? DB_ENV_ATK : DB_ENV_REL;
        env = ecoef * env + (1.0f - ecoef) * v;

        /* Comparator input low-pass (loose, not a clean pitch tracker) plus
         * fixed hysteresis: harmonic content from distortion still causes
         * extra zero-crossings and multi-triggers the divider. */
        plp += DB_PITCH_LP_COEF * (a - plp);
        if (sign >= 0) {
            if (plp < -DB_HYST_BASE) sign = -1;
        } else {
            if (plp > DB_HYST_BASE) {
                sign = 1;
                ff1 = 1 - ff1;               /* /2 */
                if (ff1) ff2 = 1 - ff2;      /* /4 */
            }
        }

        float gate = (env > DB_GATE_THR) ? env : 0.0f;
        float osq = ff2 ? 1.0f : -1.0f;
        float ofuzz = db_soft(osq * gate * 4.0f);
        olp += DB_OCT_LP_COEF * (ofuzz - olp);
        float b = olp;

        /* Filter high-shelf: applies ONLY to the distortion branch `a`,
         * never to the octave branch `b`. Real circuit: the octave runs
         * parallel to the (tone-shaped) distortion and joins at the final
         * blend, so Filter is strictly the Grunge's tone control -- it
         * must not color the octave's low end. Single band above ~3 kHz
         * (highpass = signal minus its own low-pass), boosted or cut by
         * `shelf` -- one op-amp, one pot, matching the real U2A/P2
         * "SAW (HIGH)" stage. */
        hiLP += DB_HIGH_SHELF_COEF * (a - hiLP);
        float highs = a - hiLP;
        float aToned = a + shelf * highs;

        /* blend, output -- Dust is the ONLY control that lets any of the
         * octave branch `b` into the mix; at dust=0 this is exactly the
         * tone-shaped distortion, no octave, regardless of Motor. */
        float mix = aToned * (1.0f - dust) + b * dust;

        float y = mix * outGain;
        if (y > 1.0f) y = 1.0f;
        else if (y < -1.0f) y = -1.0f;

        fxBuf[i]     = y;
        fxBuf[i + 8] = y;
    }

    st->hp = hp; st->ilp = ilp;
    st->env = env; st->plp = plp; st->olp = olp;
    st->hiLP = hiLP;
    st->sign = sign; st->ff1 = ff1; st->ff2 = ff2;
}
