/* Experimental native-rate neural test, not a sample-rate-correct NAM port.
 * No writable globals. State belongs to the instance's ctx[3] arena.
 * The generated kernel is forcibly inlined to avoid outlined audio helpers.
 */
#include <stdint.h>
#include "zoom_params.h"
#include "nam_kernel_pedal.h"
#ifdef NAM_TONE_STACK
#include "nam_tone_stack.h"
#endif
#ifdef NAM_GATE
#include "nam_gate.h"
#endif

#ifdef NAM_PAD_FLOATS
/* Size probe only: dead read-only bytes that make the file bigger without
 * changing the audio (read once at the end of warm-up, multiplied by 0). */
static const volatile float nam_pad[NAM_PAD_FLOATS] = {0};
#endif
#if defined(NAM_FAST_IO) && !(defined(NAM_TONE_STACK) && defined(NAM_GATE) && defined(NAM_BLOCK_KERNEL))
#error "NAM_FAST_IO is written for the block kernel with tone stack and gate"
#endif
#ifdef NAM_FAST_IO
/* Branch-free clip to +-1: (|v+1| - |v-1|) / 2. ABSSP on the DSP, no
 * compare-and-select, so a loop using it has no data-dependent predicate and
 * may be software-pipelined safely (docs/SAFE-DSP-RULES.md). Differs from a
 * compare clip only by rounding (~1e-7) inside +-1. */
#ifdef __TI_COMPILER_VERSION__
#define NAM_ABS(x) _fabsf(x)
#else
#include <math.h>
#define NAM_ABS(x) fabsf(x)
#endif
#define NAM_CLIP1(v) (0.5f * (NAM_ABS((v) + 1.0f) - NAM_ABS((v) - 1.0f)))
#include "nam_resample.h"   /* Eco's cubic resampling and the soft output limiter (0.26) */
#endif
#define NAM_MAGIC 0x4e414d32u
#if defined(NAM_EXACT_RINGS) && defined(NAM_TONE_STACK) && defined(NAM_GATE)
#define NAM_VERSION 6u        /* + gate state; 6: Eco resampler state (0.26) */
#elif defined(NAM_EXACT_RINGS) && defined(NAM_TONE_STACK)
#define NAM_VERSION 4u        /* + tone-stack state */
#elif defined(NAM_EXACT_RINGS)
/* State layout changed (per-layer ring positions, exactly sized rings): a new
 * version forces re-init instead of reading an old power-of-two layout. */
#define NAM_VERSION 3u
#elif defined(NAM_BLOCK_KERNEL)
#define NAM_VERSION 2u
#else
#define NAM_VERSION 1u
#endif
#define NAM_HISTORY (sizeof(((NamState *)0)->history) / sizeof(float))
#ifdef NAM_SPLIT
/* Split routing (0.26), written by the loader: how much amp each side gets,
 * {1, 0} = amp L / dry R, {0, 1} = dry L / amp R. Factors, not a route number:
 * a float->int conversion and compares here mis-ran in the emulator (the amp
 * side read gain 0). The 4th value is a marker the loader finds the table by.
 * volatile: read at run time, never folded. */
static const volatile float nam_split_route[4] = {1, 0, 0, 27182.818f};
#endif
#ifdef NAM_ECO_EQ
/* Eco+ (0.26): at half rate the network makes less treble; three biquads
 * (b0 b1 b2 a1 a2, normalised; a shelf and two peaks) put it back. The
 * loader fits them for each capture (nam_response.js) and writes them over
 * this identity default; the 16th value is a marker it finds them by.
 * volatile: the compiler must not fold the identity default away. */
static const volatile float nam_eco_eq[16] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 16180.339f};
#endif
typedef struct {
    unsigned magic, version, clear_index, ready, warm;
    float mix, input, output;
#ifdef NAM_RATE_STEPS
    NamEcoState eco;          /* resampler history: last inputs and model outputs (0.26) */
#ifdef NAM_ECO_EQ
    float eco_z[6];           /* Eco+ correction biquad state */
#endif
#endif
#ifdef NAM_SPLIT
    float dry_g, split_pad;   /* split: smoothed gain of the dry side */
#endif
#ifdef NAM_TONE_STACK
    float eq[6];              /* bass, middle, treble biquad state (2 each) */
#endif
#ifdef NAM_GATE
    float gate_env, gate_g;   /* input envelope (mean square), current gain */
    unsigned gate_hold, gate_pad;
#endif
    NamState net;
} PedalNam;

#pragma CODE_SECTION(Fx_FLT_NAMLite, ".audio")
void Fx_FLT_NAMLite(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    uintptr_t base, end;
    PedalNam *st;
    float mix, input, output;
    unsigned i;
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base || end - base < 8u) return;
    /* Align inside the supplied arena instead of rejecting a 4-aligned base. */
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(PedalNam)) return;
    st = (PedalNam *)base;
    if (params[0] < 0.5f) {
        if (st->magic == NAM_MAGIC && st->version == NAM_VERSION) {
            st->mix = 0; st->warm = 0;
        }
        return;
    }
    if (st->magic != NAM_MAGIC || st->version != NAM_VERSION) {
        st->magic = NAM_MAGIC; st->version = NAM_VERSION;
        st->clear_index = 0; st->ready = 0; st->warm = 0;
        st->mix = 0; st->input = 1; st->output = 0.5f;
        st->net.pos = 0;
#ifdef NAM_EXACT_RINGS
        /* Each layer wraps its own position in [0, n); garbage here would index
         * outside the ring. The kernel also guards, but start clean. */
        for (i = 0; i < sizeof(st->net.lpos) / sizeof(st->net.lpos[0]); ++i)
            st->net.lpos[i] = 0;
#endif
#ifdef NAM_RATE_STEPS
        for (i = 0; i < sizeof(st->eco) / sizeof(float); ++i) ((float *)&st->eco)[i] = 0;   /* no garbage into the curves */
#ifdef NAM_ECO_EQ
        for (i = 0; i < 6u; ++i) st->eco_z[i] = 0;
#endif
#endif
#ifdef NAM_SPLIT
        st->dry_g = 1.0f; st->split_pad = 0;
#endif
#ifdef NAM_TONE_STACK
        for (i = 0; i < 6u; ++i) st->eq[i] = 0;
#endif
#ifdef NAM_GATE
        st->gate_env = 0; st->gate_g = 1; st->gate_hold = NAM_GATE_HOLD; st->gate_pad = 0;
#endif
    }
    if (!st->ready) {
        unsigned stop = st->clear_index + 512u;
        if (stop > NAM_HISTORY) stop = NAM_HISTORY;
        for (i = st->clear_index; i < stop; ++i) st->net.history[i] = 0;
        st->clear_index = stop;
        if (stop == NAM_HISTORY) {
            st->ready = 1;
#ifdef NAM_PAD_FLOATS
            st->mix = 0.0f * nam_pad[NAM_PAD_FLOATS - 1];
#endif
        }
        return;
    }
#ifdef NAM_SPLIT
    mix = 1.0f;               /* split: the amp side is fully wet; knob 3 is the dry side's level */
#else
    mix = zoom_param_norm01(params[7], 0);
#endif
    input = 2.0f * zoom_param_norm01(params[5], 0.5f);
    /* Fine attenuation for high-gain captures: 1=-68dB, 5=-40dB,
     * 10=-28dB, 25=-12dB, 50=unity. Above unity keep the old law.
     * This changes drive calibration, not the network or output level. */
    if (input < 1.0f) input *= input;
    output = 2.0f * zoom_param_norm01(params[6], 0.25f);
#ifdef NAM_TONE_STACK
    /* Knobs 4-6. Rows chosen once per callback; 0.5 (knob 50) is flat. */
    const float *eq_bass   = nam_tone_row(0u, zoom_param_norm01(params[8],  0.5f));
    const float *eq_middle = nam_tone_row(1u, zoom_param_norm01(params[9],  0.5f));
    const float *eq_treble = nam_tone_row(2u, zoom_param_norm01(params[10], 0.5f));
#endif
    /* Mix=0 is a CPU-off baseline once the short fade reaches zero. */
    if (mix == 0 && st->mix < 0.0001f) {
        st->mix = 0;
        return;
    }
#ifdef NAM_BLOCK_KERNEL
#ifdef NAM_GATE
    /* See nam_gate.h. Everything here is scalar per callback; the only loop is
     * a predicate-free sum of squares. */
    float gate_gg, gate_step;
    {
        int k = (int)(zoom_param_norm01(params[11], 0) * 100.0f + 0.5f);

        float e = 0, env = st->gate_env, g0 = st->gate_g, g1, target;
        for (i = 0; i < 8u; ++i) { float s = (fx[i] + fx[i+8]) * 0.5f; e += s * s; }
        e *= 0.125f;
        if (!(e <= 4.0f)) e = 4.0f;                  /* also catches NaN */
        env += (e > env ? NAM_GATE_RISE : NAM_GATE_FALL) * (e - env);
        st->gate_env = env;
        if (k > 100) k = 100;
        if (k <= 0 || env > (st->gate_hold ? 0.25f : 1.0f) * nam_gate_thr[k])
            st->gate_hold = NAM_GATE_HOLD;
        else if (st->gate_hold)
            --st->gate_hold;
        target = st->gate_hold ? 1.0f : 0.0f;
        g1 = g0 + (target > g0 ? NAM_GATE_OPEN : NAM_GATE_CLOSE) * (target - g0);
        if (g1 > 0.9999f) g1 = 1.0f;                 /* settle exactly: open == no gate */
        if (g1 < 1.0e-5f) g1 = 0;
        st->gate_g = g1;
        gate_gg = g0;
        gate_step = (g1 - g0) * 0.125f;               /* exactly 0 when settled */
    }
#endif
#ifdef NAM_FAST_IO
    /* ONE predicate-free input loop for warm-up and steady state alike. The
     * classic loop below ran strictly serially (ii 53) because of its clip and
     * warm-up predicates. 0.24 kept both and froze the pedal on load: it was
     * the first effect over the ZDL size cap (see docs/SAFE-DSP-RULES.md,
     * "Size cap"). The warm-up zeroing is a per-callback mask now; output is
     * muted (mix target 0) until warm anyway, so the 0-7 sample shift of the
     * first non-zero input is inaudible. */
    {
        float in_g = st->input, out_g = st->output;
        const float wmask = st->warm >= 8192u ? 1.0f : 0.0f;
        const float * restrict src = fx;
        for (i = 0; i < 8u; ++i) {
            float x;
            in_g += 0.002f * (input - in_g);
            out_g += 0.002f * (output - out_g);
            x = (src[i] + src[i+8]) * 0.5f * in_g;
            st->net.input[i] = NAM_CLIP1(x) * wmask;
            gate_gg += gate_step;
            st->net.gain[i] = out_g * gate_gg;
        }
        st->input = in_g; st->output = out_g;
    }
#else
    for (i = 0; i < 8; ++i) {
        float x;
        st->input += 0.002f * (input - st->input);
        st->output += 0.002f * (output - st->output);
        x = (fx[i] + fx[i+8]) * 0.5f * st->input;
        if (x > 1) x = 1;
        if (x < -1) x = -1;
        st->net.input[i] = st->warm+i < 8192u ? 0 : x;
#ifdef NAM_GATE
        gate_gg += gate_step;
        st->net.gain[i] = st->output * gate_gg;
#else
        st->net.gain[i] = st->output;
#endif
    }
#endif /* NAM_FAST_IO */
#ifdef NAM_RATE_STEPS
    /* Run the network NAM_RATE_STEPS times per 8-sample callback instead of 8.
     *
     * WHY. NAMTime measured code 5 on hardware: the kernel alone averages at or
     * above a whole callback interval, so the pedal cannot finish before the
     * next block arrives and drops pieces of audio. Those dropped pieces are the
     * crackling. No full-rate scheduling variant closed it -- the best of seven
     * screened was 17,279 cycles against 18,612, about 7%, where roughly 2x was
     * needed. Running the network less often closes it, and cost scales with
     * NAM_RATE_STEPS.
     *
     * THE TRADE, measured on the TREC capture against full rate (4-8 kHz band):
     *   7/8  -2.4 dB    6/8  -12.3 dB    5/8  -20.4 dB    4/8  -27.0 dB
     * Very non-linear: 7/8 is nearly transparent and most of the loss arrives
     * below it. The dullness is NOT poor resampling -- cubic interpolation or
     * dropping the anti-alias average moved that band by under 2 dB. It is the
     * network generating less high content, because its dilated receptive field
     * is a fixed number of SAMPLES and so spans more time at a lower rate.
     *
     * HOW (0.26). Resample 8 -> N and N -> 8 with 4-point cubic curves at exact,
     * even positions (nam_resample.h). Until 0.25: a 2-tap average at the
     * uneven positions floor(8i/N) and linear interpolation back, which left
     * spurs (-22.8 dB at 3 kHz). Indices and fractions come from integer
     * arithmetic on constants: no runtime divide, and no float->unsigned cast
     * (which pulls in __c6xabi_fixfu -- a documented freeze, see Mangle in
     * LOADER-SAFETY.md). The generated kernel is unchanged. */
    nam_eco_down(&st->eco, st->net.input, NAM_RATE_STEPS);   /* cubic, even positions (nam_resample.h) */
    nam_block(&st->net,NAM_RATE_STEPS);
    nam_eco_up(&st->eco, st->net.output, NAM_RATE_STEPS);
#ifdef NAM_ECO_EQ
    {   /* Eco+ correction, at 44.1 kHz after the upsampling */
        float c[15];
        for (i = 0; i < 15u; ++i) c[i] = nam_eco_eq[i];
        for (i = 0; i < 8u; ++i) {
            float y = st->net.output[i];
            y = nam_biquad(c, st->eco_z, y);
            y = nam_biquad(c + 5, st->eco_z + 2, y);
            st->net.output[i] = nam_biquad(c + 10, st->eco_z + 4, y);
        }
    }
#endif
#else
    nam_block(&st->net,8);
#endif
#ifdef NAM_TONE_STACK
    {
        /* Range check on the RAW network output, then Bass -> Mid -> Treb (the
         * NAM plugin's order), in one clean 8-sample loop.
         *
         * WHY HERE and not in the output loop below: that loop has an early
         * return, which stops the compiler overlapping iterations, so the three
         * recursive filters ran strictly back to back -- measured +485 cycles.
         * Here the bands can overlap across samples.
         *
         * The check is BRANCH-FREE: comparison results OR'd into a flag, no
         * predicated work, reset after the loop. That keeps the rule learned
         * from the exact-ring bug -- no data-dependent predicate inside a
         * pipelined loop. It runs BEFORE the EQ because a +20 dB boost can
         * push a healthy signal past 16. (y != y) catches NaN. */
        /* One combined loop, always run. Measured against one loop per band
         * that skips untouched bands: combined +345 cycles in every setting;
         * per-band +294 flat, +461 treble-only, +790 all three -- separate loops
         * cannot overlap the three recursive filters and each pays its own
         * start-up. The combined loop wins everywhere it matters. */
        unsigned bad = 0;
#ifdef NAM_FAST_IO
        /* All three knobs at 50: each band is an exact identity once its state
         * is zero, so skip the filters and keep only the range check. ~200
         * cycles, for chains where a cab after NAM does the tone shaping. */
        if (eq_bass == nam_tone_row(0u, 0.5f) && eq_middle == nam_tone_row(1u, 0.5f) && eq_treble == nam_tone_row(2u, 0.5f)) {
            for (i = 0; i < 6u; ++i) st->eq[i] = 0;
            for (i = 0; i < 8u; ++i) {
                float y = st->net.output[i];
                bad |= (unsigned)(y < -16.0f) | (unsigned)(y > 16.0f) | (unsigned)(y != y);
            }
        } else
#endif
        for (i = 0; i < 8u; ++i) {
            float y = st->net.output[i];
            bad |= (unsigned)(y < -16.0f) | (unsigned)(y > 16.0f) | (unsigned)(y != y);
            y = nam_biquad(eq_bass, st->eq, y);
            y = nam_biquad(eq_middle, st->eq + 2, y);
            y = nam_biquad(eq_treble, st->eq + 4, y);
            st->net.output[i] = y;
        }
        if (bad) { st->magic = 0; return; }   /* clear again next callback */
    }
#endif
#endif
#if defined(NAM_GATE) && !defined(NAM_TONE_STACK)
#error "the gate is only wired into the tone-stack engine"
#endif
#if defined(NAM_TONE_STACK) && !defined(NAM_BLOCK_KERNEL)
#error "the tone stack is only wired into the block kernel"
#endif
#ifdef NAM_FAST_IO
    /* ONE predicate-free output loop. The range check already ran (branch-
     * free, pre-EQ, in the tone-stack loop) and the stable EQ keeps a checked
     * input finite, so no early return is needed; the mix target is 0 until
     * warm, which keeps warm-up exactly dry (mix starts at 0 and stays 0). */
    {
        float m = st->mix;
        const float target = st->warm >= 8192u ? mix : 0.0f;
#ifdef NAM_SPLIT
        /* Split (0.26): the amp on one output, the dry guitar on the other.
         * Which side is chosen in the loader and written over nam_split_route
         * as two factors ({1, 0} = amp L / dry R, {0, 1} = dry L / amp R). Knob 3, "Dry" in split
         * files, is the dry side's level: -24 dB .. +24 dB in even dB steps,
         * 50 = unchanged (a clean guitar is much quieter than the amp).
         * Chosen once per callback and applied as factors, so the loop stays
         * predicate-free. */
        const float wet_l = nam_split_route[0], wet_r = nam_split_route[1];
        float dg_t, dg = st->dry_g;
        {   /* 2^(8u - 4), u = 0..1: the exponent's integer part into the float's
             * exponent bits, a cubic for the fraction (<0.1%); no pow() helper */
            float x = zoom_param_norm01(params[7], 0.5f) * 8.0f, f;
            int n = (int)x;
            union { float f; unsigned u; } e;
            f = x - (float)n;
            e.u = (unsigned)(n - 4 + 127) << 23;
            dg_t = e.f * (1.0f + f * (0.6951f + f * (0.2262f + f * 0.0787f)));
        }
#endif
        float ys[8];
        /* Level, then the soft limiter (exact below 0.75, then soft to +-1;
         * 0.26), in a loop of its own: the mix loop below cannot overlap
         * iterations (the mix ramp), so work inside it costs its full latency. */
        for (i = 0; i < 8u; ++i) ys[i] = nam_soft(st->net.output[i] * st->net.gain[i]);
        for (i = 0; i < 8u; ++i) {
            float l = fx[i], r = fx[i+8], y = ys[i];
            m += 0.002f * (target - m);
#ifdef NAM_SPLIT
            dg += 0.002f * (dg_t - dg);
            {   /* the dry side takes the Dry level; the amp side is as before */
                float gl = wet_l + (1.0f - wet_l) * dg, gr = wet_r + (1.0f - wet_r) * dg;
                l *= gl; r *= gr;
            }
            fx[i] = l + (m * wet_l) * (y - l);
            fx[i+8] = r + (m * wet_r) * (y - r);
#else
            fx[i] = l + m * (y - l);
            fx[i+8] = r + m * (y - r);
#endif
        }
        st->mix = m;
#ifdef NAM_SPLIT
        st->dry_g = dg;
#endif
        if (st->warm < 8192u) st->warm += 8u;       /* 8192 is a multiple of 8 */
    }
#else
    for (i = 0; i < 8; ++i) {
        float l = fx[i], r = fx[i+8], y, target;
#ifdef NAM_BLOCK_KERNEL
        y = st->net.output[i];
#else
        float x;
        st->input += 0.002f * (input - st->input);
        st->output += 0.002f * (output - st->output);
        x = (l + r) * 0.5f * st->input;
        if (x > 1) x = 1;
        if (x < -1) x = -1;
        /* Warm at the normal 8-sample callback pace, never a long init loop. */
        if (st->warm < 8192u) x = 0;
        y = nam_sample(&st->net, x);
#endif
#ifndef NAM_TONE_STACK
        if (!(y >= -16 && y <= 16)) {
            st->magic = 0; /* Clear again next callback after invalid output. */
            return;
        }
#else
        /* The real range check ran pre-EQ, in the tone-stack loop. This one
         * only catches non-finite values -- the EQ cannot reach 1e4 from a
         * checked |y| <= 16 -- but it is here for its EARLY RETURN as much as
         * for its check. That return is what keeps this loop out of software
         * pipelining, and the body has per-sample predicates (warm-up counter,
         * clip): the exact shape that miscompiled or mis-emulated in the
         * exact-ring work. Without it this loop was pipelined and a flat EQ
         * stopped being bit-identical to NAMFull2 on the TI build (max diff
         * 0.09), though it still was on the host. */
        if (!(y >= -1.0e4f && y <= 1.0e4f)) {
            st->magic = 0;
            return;
        }
#endif

        if (st->warm < 8192u) ++st->warm;
        target = (st->warm >= 8192u) ? mix : 0;
        st->mix += 0.002f * (target - st->mix);
#ifdef NAM_BLOCK_KERNEL
        y *= st->net.gain[i];
#else
        y *= st->output;
#endif
        if (y > 1) y = 1;
        if (y < -1) y = -1;
        fx[i] = l + st->mix * (y - l);
        fx[i+8] = r + st->mix * (y - r);
    }
#endif /* NAM_FAST_IO */
}
