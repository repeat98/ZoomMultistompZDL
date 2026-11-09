# Redraw (test A)

Does the MS-70CDR redraw an effect's screen on its own, or only on events?
Knobs 1 and 2 show the DSP's cycle counter (TSCL) as their value text; the UI
calls the value-text callbacks while it draws. Audio passes through.

    python3 src/hardware_probes/redraw/build.py      # -> dist/Redraw.ZDL (gitignored)

| Knob | Shows | Moves |
|---|---|---|
| Slow | `TSCL >> 24`, 2 hex digits | ~18 steps/s, wraps every ~14 s |
| Fast | `(TSCL >> 12) & 0xFFF`, 3 hex digits | different on every call |
| Plain | its value | only when turned |

Reading it:
- **Digits change with hands off** -> the screen refreshes periodically; label
  text can animate and test B is worth doing.
- **Digits change only when a knob turns** -> event-driven; note whether turning
  *Plain* also refreshes Slow/Fast (whole-screen redraw) or not.
- **Always the same digits** -> TSCL isn't running on this firmware; the test is
  inconclusive and needs a counter in memory instead.

FXID 411 (unused).

**Result (MS-70CDR 2.10, 2026-10-17): event-driven.** On the knob page the
Slow/Fast values stay frozen with hands off and change when the knobs are
turned. TSCL runs (the digits differ per redraw), so the screen is redrawn only
on events: no periodic refresh on stock firmware.
