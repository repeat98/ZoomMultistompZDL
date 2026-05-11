#ifndef ZOOM_PARAMS_H
#define ZOOM_PARAMS_H

/*
 * Audio-side helpers for the current stock-derived edit handlers.
 *
 * The handlers write a small raw float to params[5..13] (roughly 0..0.14
 * at the knob rail). Descriptor max/default control the pedal UI, but
 * DSP code should explicitly normalize and scale the raw value here.
 */
#define ZOOM_PARAM_RAW_MAX 0.14f
#define ZOOM_PARAM_RAW_TO_NORM (1.0f / ZOOM_PARAM_RAW_MAX)

static inline float zoom_clamp01(float x)
{
    if (x < 0.0f) return 0.0f;
    if (x > 1.0f) return 1.0f;
    return x;
}

static inline float zoom_param_norm(float raw, float fallback_norm)
{
    float v = raw * ZOOM_PARAM_RAW_TO_NORM;
    if (v <= 0.0001f) return zoom_clamp01(fallback_norm);
    return zoom_clamp01(v);
}

static inline float zoom_param_scale(float raw, float fallback_norm, float out_min, float out_max)
{
    float n = zoom_param_norm(raw, fallback_norm);
    return out_min + (out_max - out_min) * n;
}

static inline int zoom_param_switch(float raw, int fallback_on)
{
    if (raw <= 0.0001f) return fallback_on ? 1 : 0;
    return raw >= (ZOOM_PARAM_RAW_MAX * 0.5f);
}

#endif
