/* CoverRW: test C of docs/pedal-research/animated-covers.md.
 *
 * Does the pedal re-read an effect's cover picture each time it redraws, or
 * keep a copy decoded when the effect was selected? The cover (built by
 * build.py) holds a band of literal RLE bytes, 0xFE 0xFD 0xFE ... (nearly solid
 * black), between blank columns. On each on/off flip the audio code inverts the
 * band once (0x01 0x02 ...: nearly white): every byte stays different from its
 * neighbours, so the RLE length and the rest of the picture are unchanged.
 *
 * Writes go to the effect's own cover in .const (flagged read-only, but in
 * RAM and written by the loader). Knob 1's value text reads the first byte
 * back, so the write is visible even if the screen keeps an old copy.
 * Audio passes through. State (last on/off) lives in the instance arena. */
#include <stdint.h>
#include "coverrw_layout.h"      /* COVER_FLIP_OFF, COVER_FLIP_LEN (from build.py) */

extern unsigned char _Fx_DLY_CoverRW_Pic[];   /* resolved by the linker to the cover */

#define MAGIC 0x43565257u                     /* 'CVRW' */
typedef struct { unsigned magic, prev, flips; } CoverState;

static const char HEX[16] = {'0','1','2','3','4','5','6','7','8','9','A','B','C','D','E','F'};

int ZDL_GetLabel_0(unsigned int value, char *out)
{
    unsigned v = ((volatile unsigned char *)_Fx_DLY_CoverRW_Pic)[COVER_FLIP_OFF];
    (void)value;
    out[0] = HEX[v >> 4]; out[1] = HEX[v & 15u]; out[2] = 0;
    return 2;
}

#pragma CODE_SECTION(Fx_DLY_CoverRW, ".audio")
void Fx_DLY_CoverRW(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    uintptr_t base, end;
    CoverState *st;
    unsigned on, i;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(CoverState)) return;
    st = (CoverState *)base;
    on = params[0] >= 0.5f;
    if (st->magic != MAGIC) { st->magic = MAGIC; st->prev = on; st->flips = 0; return; }
    if (on == st->prev) return;
    st->prev = on;
    {
        volatile unsigned char *p = (volatile unsigned char *)_Fx_DLY_CoverRW_Pic + COVER_FLIP_OFF;
        for (i = 0; i < COVER_FLIP_LEN; ++i) p[i] ^= 0xFFu;
    }
    st->flips++;
}
