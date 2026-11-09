#ifndef ZOOM_PARAMS_H
#define ZOOM_PARAMS_H

/* Shared handlers supply normalized 0..1 values. Legacy probes may explicitly
 * use zoom_param_norm for the old 0..0.14 contract; never auto-detect that range. */
#define ZOOM_PARAM_RAW_MAX 0.14f
#define ZOOM_PARAM_RAW_TO_NORM (1.0f / ZOOM_PARAM_RAW_MAX)

/*
 * `static inline` is a HINT here, not a guarantee, and the difference is fatal
 * rather than cosmetic. Past a certain number of call sites the compiler's
 * code-growth heuristic outlines these into real CALLed functions in .text --
 * outside .audio, reached by a CALL -- which hard-freezes the DSP. Rewire hit it
 * at eight knobs: identical source built clean at seven, and at eight emitted
 * zoom_param_norm01 as a function with no warning of any kind. Only the object
 * file's section table showed it.
 *
 * Pinning them costs nothing where they were already inlined, which is every
 * effect in the pack today, and removes the cliff for anything built later.
 */
#define ZOOM_DO_PRAGMA(x) _Pragma(#x)
#define ZOOM_ALWAYS_INLINE(f) ZOOM_DO_PRAGMA(FUNC_ALWAYS_INLINE(f))

ZOOM_ALWAYS_INLINE(zoom_clamp01)
static inline float zoom_clamp01(float x)
{
    if (!(x >= 0.0f)) return 0.0f;
    if (x > 1.0f) return 1.0f;
    return x;
}

ZOOM_ALWAYS_INLINE(zoom_param_norm)
static inline float zoom_param_norm(float raw, float fallback_norm)
{
    float v = raw * ZOOM_PARAM_RAW_TO_NORM;
    if (!(raw >= 0.0f && raw <= 100.0f)) return zoom_clamp01(fallback_norm);
    return zoom_clamp01(v);
}

/* Hardware reality (confirmed via StChorus + on-pedal testing of this pack):
 * the spliced LineSel / synthesized-handler path delivers a NORMALIZED 0..1
 * raw value, NOT the 0..0.14 the older GAIN probe saw. Using zoom_param_norm
 * (the x7 helper) saturates every knob to max above ~14% travel — i.e. the
 * knobs feel dead and levels pin loud. Use this 0..1 scaler instead. */
ZOOM_ALWAYS_INLINE(zoom_param_norm01)
static inline float zoom_param_norm01(float raw, float fallback_norm)
{
    if (!(raw >= 0.0f && raw <= 100.0f)) return zoom_clamp01(fallback_norm);
    if (raw <= 1.0f) return zoom_clamp01(raw);
    return zoom_clamp01(raw * 0.01f);
}

ZOOM_ALWAYS_INLINE(zoom_param_scale)
static inline float zoom_param_scale(float raw, float fallback_norm, float out_min, float out_max)
{
    float n = zoom_param_norm(raw, fallback_norm);
    return out_min + (out_max - out_min) * n;
}

ZOOM_ALWAYS_INLINE(zoom_param_switch)
static inline int zoom_param_switch(float raw, int fallback_on)
{
    if (!(raw >= 0.0f && raw <= 100.0f)) return fallback_on ? 1 : 0;
    return raw >= (ZOOM_PARAM_RAW_MAX * 0.5f);
}

#endif
