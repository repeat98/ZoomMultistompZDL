/* Redraw: test A of docs/pedal-research/animated-covers.md.
 *
 * Question: does the pedal redraw an effect's screen by itself, or only on
 * events (knob turns, edits)? The value text of knobs 1 and 2 comes from these
 * callbacks, which the UI calls while drawing, and shows the DSP's free-running
 * cycle counter. If the digits move while nothing is touched, the screen is
 * refreshed periodically; if they move only when a knob turns, it is not.
 *
 * Audio passes through untouched. No memory is written except the label buffer
 * the UI hands us; no globals, no helpers (hex output avoids division). */
#include <stdint.h>
#include <c6x.h>

static const char HEX[16] = {'0','1','2','3','4','5','6','7','8','9','A','B','C','D','E','F'};

static int put_hex(char *out, unsigned v, int digits)
{
    int i;
    for (i = 0; i < digits; ++i)
        out[i] = HEX[(v >> (4 * (digits - 1 - i))) & 15u];
    out[digits] = 0;
    return digits;
}

/* Knob 1 "Slow": TSCL >> 24, ~18 steps a second at ~300 MHz. */
int ZDL_GetLabel_0(unsigned int value, char *out) { (void)value; return put_hex(out, TSCL >> 24, 2); }
/* Knob 2 "Fast": a fast-moving slice; different on every call. */
int ZDL_GetLabel_1(unsigned int value, char *out) { (void)value; return put_hex(out, (TSCL >> 12) & 0xFFFu, 3); }

#pragma CODE_SECTION(Fx_DLY_Redraw, ".audio")
void Fx_DLY_Redraw(uintptr_t *ctx)
{
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    *magic_dst = *magic_src;            /* the host's handshake word, as every effect */
}
