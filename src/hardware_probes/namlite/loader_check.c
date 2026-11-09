/* NAMLite loader isolation: same identity/controls, no neural code or arena. */
#include <stdint.h>
#include "zoom_params.h"
#pragma CODE_SECTION(Fx_FLT_NAMLite, ".audio")
void Fx_FLT_NAMLite(uintptr_t *ctx)
{
    float *p = (float *)ctx[1];
    float *fx = (float *)ctx[5];
    unsigned int *src = (unsigned int *)ctx[12];
    unsigned int *dst = *(unsigned int **)ctx[11];
    float input, output, mix, gain;
    int i;
    *dst = *src;
    if (p[0] < 0.5f) return;
    input = 2.0f * zoom_param_norm01(p[5], 0.5f);
    output = 2.0f * zoom_param_norm01(p[6], 0.25f);
    mix = zoom_param_norm01(p[7], 0);
    gain = 1.0f + mix * (input * output - 1.0f);
    for (i = 0; i < 16; ++i) fx[i] *= gain;
}
