#ifndef TAPE_CONTROLS_H
#define TAPE_CONTROLS_H
#include "zoom_params.h"

/* Custom Oxide/Spool voicing, not upstream Airwindows control laws. */
ZOOM_ALWAYS_INLINE(oxide_drive_denominator)
static inline float oxide_drive_denominator(float gain)
{
    float excess = gain - 1.0f;
    if (excess < 0.0f) excess = 0.0f;
    /* Leave attenuation and unity alone; reduce the level lift above unity.
     * At 4x drive, compensation is 1/3.25; Output remains an independent trim. */
    return 1.0f + excess * 0.75f;
}

ZOOM_ALWAYS_INLINE(spool_feedback)
static inline float spool_feedback(float knob)
{
    float n = zoom_clamp01(knob);
    float end = n - 0.8f;
    if (end < 0.0f) end = 0.0f;
    /* Continuous value and slope at 80; unity crossed around 92.
     * Saturation in the record path bounds the high-feedback region. */
    return n * (0.6f + 0.4f * n) + 10.0f * end * end;
}
#endif
