/* Blink: test D of docs/pedal-research/animated-covers.md.
 *
 * Tests A and C showed the screen redraws only on events, and that an effect
 * can rewrite its own cover (the firmware re-decodes it on every redraw). This
 * asks the firmware to redraw: while the effect is on, every 0.5 s it inverts
 * a band in its cover (as CoverRW) and calls the UI task's Event_post with the
 * redraw bit 0x01. Addresses: MIDISTOMP (matujuice/zoom-ms-midistomp docs/
 * ms70cdr-addresses.md); bit 0x01 and the 30-50 fps result from the audio
 * callback: Leemuzhko/ZOOM_development SDK/EFFECT_UI_WRITES.md (hardware). If the band blinks with hands
 * off, an effect can animate the screen on stock firmware.
 *
 * Firmware-specific, so it checks first and otherwise calls nothing:
 *   - the first 20 bytes at Event_post must match MS-70CDR 2.10;
 *   - the UI event handle (OS B14 + 656 = 0xC00EF9D8) must point into RAM.
 * Event_post reaches its globals by absolute address (no B14), see
 * firmware/extracted/main_os.dis at 0xc00cbf40. At most one call per 0.5 s,
 * never while the effect is off. Audio passes through. */
#include <stdint.h>
#include <c6x.h>
#include "blink_layout.h"        /* COVER_FLIP_OFF, COVER_FLIP_LEN (from build.py) */

extern unsigned char _Fx_DLY_Blink_Pic[];      /* resolved by the linker to the cover */

#define EVENT_POST_ADDR 0xC00CBF40u
#define UI_EVENT_SLOT   0xC00EF9D8u            /* OS B14 (0xC00EF748) + 656 */
#define EV_REDRAW       0x01u                  /* redraws page + cover (Leemuzhko SDK, hardware); MIDISTOMP's 0x40 may not */
#define PERIOD          2756u                  /* 8-sample callbacks per 0.5 s at 44.1 kHz */
#define MAGIC           0x424C4E4Bu            /* 'BLNK' */

typedef void (*event_post_fn)(void *event, unsigned mask);
typedef struct { unsigned magic, count, ok, posts; } BlinkState;

static const unsigned SIG[5] = { 0x27773577u, 0x85778677u, 0xB64631F7u, 0x02E7442Bu, 0x01E74228u };
static const char HEX[16] = {'0','1','2','3','4','5','6','7','8','9','A','B','C','D','E','F'};

static int in_ram(unsigned a)
{
    return (a >= 0xC0000000u && a < 0xC8000000u) || (a >= 0x11800000u && a < 0x11840000u);
}

/* Pure reads: is this MS-70CDR 2.10 with a live UI event? */
static int firmware_ok(void)
{
    const volatile unsigned *code = (const volatile unsigned *)EVENT_POST_ADDR;
    unsigned i, ev;
    for (i = 0; i < 5u; ++i)
        if (code[i] != SIG[i]) return 0;
    ev = *(const volatile unsigned *)UI_EVENT_SLOT;
    return in_ram(ev) && (ev & 3u) == 0u;
}

int ZDL_GetLabel_0(unsigned int value, char *out)
{
    unsigned v = TSCL >> 24;
    (void)value;
    out[0] = HEX[v >> 4]; out[1] = HEX[v & 15u]; out[2] = 0;
    return 2;
}

int ZDL_GetLabel_1(unsigned int value, char *out)
{
    (void)value;
    if (firmware_ok()) { out[0] = 'O'; out[1] = 'K'; } else { out[0] = 'N'; out[1] = 'O'; }
    out[2] = 0;
    return 2;
}

#pragma CODE_SECTION(Fx_DLY_Blink, ".audio")
void Fx_DLY_Blink(uintptr_t *ctx)
{
    float *params = (float *)ctx[1];
    uintptr_t *desc = (uintptr_t *)ctx[3];
    unsigned int *magic_src = (unsigned int *)ctx[12];
    unsigned int *magic_dst = *(unsigned int **)ctx[11];
    uintptr_t base, end;
    BlinkState *st;
    unsigned i;
    *magic_dst = *magic_src;
    if (!desc) return;
    base = desc[0]; end = desc[1];
    if (!base || end <= base) return;
    base += (8u - (base & 7u)) & 7u;
    if (end - base < sizeof(BlinkState)) return;
    st = (BlinkState *)base;
    if (st->magic != MAGIC) { st->magic = MAGIC; st->count = 0; st->posts = 0; st->ok = firmware_ok(); return; }
    if (params[0] < 0.5f) return;                 /* off: no flips, no calls */
    if (++st->count < PERIOD) return;
    st->count = 0;
    {
        volatile unsigned char *p = (volatile unsigned char *)_Fx_DLY_Blink_Pic + COVER_FLIP_OFF;
        for (i = 0; i < COVER_FLIP_LEN; ++i) p[i] ^= 0xFFu;
    }
    if (st->ok) {
        void *ev = (void *)*(const volatile unsigned *)UI_EVENT_SLOT;
        ((event_post_fn)EVENT_POST_ADDR)(ev, EV_REDRAW);
        st->posts++;
    }
}
