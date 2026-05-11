#include <stdint.h>

#pragma CODE_SECTION(Fx_FLT_ToTape9_Tiny, ".audio")

void Fx_FLT_ToTape9_Tiny(unsigned int *ctx)
{
    unsigned int *magic_src = (unsigned int *)(uintptr_t)ctx[12];
    unsigned int *magic_dst = (unsigned int *)(uintptr_t)
        *(unsigned int *)(uintptr_t)ctx[11];
    *magic_dst = *magic_src;
}
