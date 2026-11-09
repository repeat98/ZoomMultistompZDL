/* Stage 1: leave the upstream FX buffer untouched (current in-place ABI).
 * Firmware handles bypass. Preserve the required context shuttle only.
 * No model, persistent state, stack buffers or audible knob processing.
 */
#include <stdint.h>
#pragma CODE_SECTION(Fx_FLT_NAMTest, ".audio")
void Fx_FLT_NAMTest(uintptr_t *ctx)
{
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    *magic_dst = *magic_src;
}
