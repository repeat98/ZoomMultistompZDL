#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_ToTape9_Tiny, ".audio")

void Fx_FLT_ToTape9_Tiny(unsigned int *ctx)
{
    unsigned int *magic_src = (unsigned int *)(uintptr_t)ctx[12];
    unsigned int *magic_dst = (unsigned int *)(uintptr_t)
        *(unsigned int *)(uintptr_t)ctx[11];
    *magic_dst = *magic_src;
}

#pragma CODE_SECTION(Fx_FLT_ToTape9_ParamProbe, ".audio")

void Fx_FLT_ToTape9_ParamProbe(unsigned int *ctx)
{
    float *params = (float *)(uintptr_t)ctx[1];
    float *fx_buf = (float *)(uintptr_t)ctx[5];
    unsigned int *magic_src = (unsigned int *)(uintptr_t)ctx[12];
    unsigned int *magic_dst = (unsigned int *)(uintptr_t)
        *(unsigned int *)(uintptr_t)ctx[11];
    *magic_dst = *magic_src;

    if (params[0] < 0.5f) return;

    float probe = params[13] * 8.0f;
    int i;
    for (i = 0; i < 16; i++) {
        fx_buf[i] = fx_buf[i] * probe;
    }
}
