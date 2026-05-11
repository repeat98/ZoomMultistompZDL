#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_Hello, ".audio")
void Fx_FLT_Hello(uint32_t *ctx) {
    // ctx[4/5/6] = dry/fx/out buffers
    float *fx  = (float *)ctx[5];
    float *out = (float *)ctx[6];
    
    // params[0] is On/Off
    float *params = (float *)ctx[1];
    float onoff = params[0];

    // Pass audio through, scaled by on/off
    for (int i = 0; i < 16; i++) {
        out[i] += fx[i] * onoff;
    }
}