/* Load-only diagnostic: retain the complete IR bank, never run convolution.
 * No state allocation/clearing, coefficient reads, or audio-buffer writes.
 */
#include <stdint.h>
#ifndef HOST_TEST
#include "ir_data.h"
#pragma RETAIN(ir_bank)
#pragma RETAIN(ir_scale)
#pragma RETAIN(ir_cos)
#pragma RETAIN(ir_sin)
#pragma RETAIN(ir_filter)
#endif
#pragma CODE_SECTION(Fx_REV_SloIR,".audio")
void Fx_REV_SloIR(uintptr_t *ctx) {
    unsigned *src=(unsigned*)ctx[12];
    unsigned *dst=*(unsigned**)ctx[11];
    *dst=*src;
}
