# Blink (test D)

Can an effect trigger screen redraws itself on stock firmware? Tests A and C
showed the MS-70CDR redraws only on events, and re-decodes an effect's cover
from its own RAM on every redraw. While switched on, Blink inverts a band in
its cover every 0.5 s and then calls the UI task's `Event_post(event, 0x01)`
(MS-70CDR 2.10: `Event_post` at `0xC00CBF40`, UI event object pointer at
`0xC00EF9D8`). Bit `0x01` redraws the parameter page and the cover; this and a
steady 30-50 fps from the audio callback are hardware results in Leemuzhko's
SDK ([EFFECT_UI_WRITES](https://github.com/Leemuzhko/ZOOM_development/blob/main/SDK/EFFECT_UI_WRITES.md));
MIDISTOMP posts `0x40`, which the SDK found does not redraw the page.

Firmware-specific, so it checks before calling anything: the first 20 bytes at
`0xC00CBF40` must match MS-70CDR 2.10 (`firmware/extracted/main_os.dis`) and
the event handle must point into RAM. Otherwise the band still flips in memory
but nothing is called. `Event_post` reaches its globals by absolute address, so
the caller's B14 doesn't matter. At most one call per 0.5 s, none while off.

| Knob | Value text |
|---|---|
| Clock | `TSCL >> 24` in hex: moves by itself only if redraws are happening |
| Check | `OK` = firmware matched, redraws are requested; `NO` = nothing is called |
| Plain | its number |

    python3 src/hardware_probes/blink/build.py      # -> dist/Blink.ZDL (gitignored)

The emulator has no firmware at those addresses and stops with "Budget" at the
first check; with the check compiled out (`-DEMU_NO_FW`) it runs clean, flips
every 2,756 blocks, audio unchanged.

Use a spare patch with Auto Save off. FXID 413.

**First build froze on selection (2026-10-17): linker bug, not the firmware
call.** The audio code's call to `firmware_ok()` (a function in `.text`) was
linked 0x80 bytes past its target: the linker added the instruction's section
offset to a cross-section CALLP (Leemuzhko's SDK documents this exact bug). The
emulator didn't catch it (with the check compiled out, the wrong jump happened
to return). Fixed in build/linker.py; Tonic rebuilds byte-identical. The only
other effect with cross-section calls is PureStDrive (zoom_sinf), which likely
explains its failure in repeat98/ZoomMultistompZDL#7.

**Result (MS-70CDR 2.10, 2026-10-18): works.** With the linker fixed, the band
blinks by itself while the effect is on (black bar on and off every 0.5 s, hands
off). An effect can animate the screen on stock firmware.
