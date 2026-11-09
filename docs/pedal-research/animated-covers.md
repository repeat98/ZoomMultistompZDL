# Animated covers and a live oscilloscope on the effect screen

Researched 2026-10-17 (MS-70CDR firmware 2.10). Question: can an effect animate
its on-pedal picture, ideally as an oscilloscope that follows the input signal?

**Short answer.** Yes, through a firmware patch: MIDISTOMP already draws a live,
effect-driven status box onto an effect's screen on MS-70CDR 2.10, flash-tested
on 2026-10-15. On stock firmware nobody has done it, and the screen only redraws
on events (knob turns, edits); two cheap probes would tell us whether a smaller
stock-firmware version is possible.

## Leemuzhko's SDK (the answer, 2026-10-17)

Alexander Lim (Leemuzhko) documents all of this, with MS-70CDR 2.10 hardware
results, in [ZOOM_development/SDK](https://github.com/Leemuzhko/ZOOM_development/tree/main/SDK),
especially [EFFECT_UI_WRITES](https://github.com/Leemuzhko/ZOOM_development/blob/main/SDK/EFFECT_UI_WRITES.md)
and [CARD_RENDERING](https://github.com/Leemuzhko/ZOOM_development/blob/main/SDK/CARD_RENDERING.md).
The repo has no licence: use its findings (credited), not its code.

- The firmware re-decodes the cover and re-reads imageInfo (picture pointer,
  control positions) on every redraw (matches our test C).
- From the audio callback, `0xC00CBF40(*(void **)0xC00EF9D8, 0x01)` wakes the
  UI task and redraws: steady 30-50 fps, no reported clicks or stalls. Bit
  `0x01` redraws the page and the cover; `0x20` alone redraws nothing.
- Full-frame animation: compose 128x64 in the arena, RLE-encode it (up to 1536
  bytes), point imageInfo word 5 at it, double-buffer (FBKILL v0.07). His
  LMDSO05 is the XY scope.
- `ctx[0]` is the effect's own slot (0-5). Effects can write their own knob
  values and On/Off (with autosave rules), and show card-only controls.
- Guard everything with a firmware check: these are absolute 2.10 addresses.

## What's established

**How the picture reaches the screen**
- The cover is a 128x64 1-bpp RLE blob at the start of the effect's `.const`
  section. The firmware finds it by pointer (the loader patches
  `effectTypeImageInfo`+0x14 to point at it), not by symbol name
  ([build/linker.py](../../build/linker.py) ~649-718; [build/ABI.md](../../build/ABI.md) 180-216).
- `.const` is flagged read-only but lives in RAM and is written by the loader
  (relocations). Whether a later write is trapped is unknown.
- No stock effect has more than one cover, and no stock code ever reads its own
  picture: all 623+ references to pictures are data pointers, none from code
  (scan of 825 stock ZDLs).
- **Stock effects already show graphics chosen at runtime**: the knob-value
  boxes are uncompressed sprites with N frames, picked by the parameter value
  (knob-info `{w, h, nframes, ?, style, sprite_ptr}`; e.g. CloneCho knob
  16x11x11 frames, TapeEcho3 slider 44x8x11). Inferred from data, not traced in
  firmware.

**The display, from MIDISTOMP's firmware work** ([zoom-ms-midistomp](https://github.com/matujuice/zoom-ms-midistomp),
[os-reverse-engineering.md](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/os-reverse-engineering.md),
[ms70cdr-addresses.md](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/ms70cdr-addresses.md))
- Framebuffer `0x11816800`: 1 bpp, column bytes (bit 0 on top), 8 pages of 128.
  A dirty byte (`0xC00EEBB0` on MS-70CDR) marks which pages to send; LCD send
  `0xC00B57C8`.
- Drawing is event-driven: the UI task redraws when bit `0x40` of its event word
  is posted (`Event_post` `0xC00CBF40` on MS-70CDR). No timer refresh found.
  The OS can animate (effect slide: 4 frames, 100 ms apart).
- Since v2.0 MIDISTOMP is built from **MS-70CDR 2.10**, with ~200 addresses
  mapped and hardware-checked, and RAM regions confirmed free
  (`0xC00F3100`-`0xC0197FFF` and others).
- **Effect-driven screen graphics already work** on MS-70CDR 2.10:
  *Looper services* ([looper-services.md](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/looper-services.md)).
  The Looper ZDL writes status text, a progress value and an invert flag to a
  shared block (`0xC00F3000`); a hook before every LCD send (`0xC00BB0EC`)
  draws a box into the framebuffer and marks it dirty; a 16 ms poll posts a
  redraw when the block changes. Flash-tested 2026-10-15 ("working well"),
  not in the v1.2 release yet. Their open issue
  [#8](https://github.com/matujuice/zoom-ms-modding/issues/8) asks for exactly
  this kind of screen feedback (levels, LFO, activity).

**Community:** no published stock-firmware effect animates its cover; no
"Doom on Zoom". ZD2 icons (newer pedals) are two sizes of one picture, not
frames.

## Oscilloscope: the design that would work

Firmware route, built on MIDISTOMP's looper pattern (MS-70CDR 2.10):

1. **Shared block** in confirmed-free RAM (e.g. next to looper services):
   magic, owner FXID, frame counter, and 128 columns of min/max (2 bytes each).
2. **Effect side** (a "Scope" effect, or a scope option in NAM/CabIR): every
   frame, fold ~1,000 input samples into 128 columns of min/max, starting at a
   rising zero crossing so the trace stands still; write the columns, then bump
   the counter. A few dozen cycles per sample; no firmware calls.
3. **Firmware side**: extend the draw hook to draw the 128 columns as vertical
   strokes into the cover area (and a smaller strip on knob pages), only when
   the effect under the cursor owns the block; mark the pages dirty. The 16 ms
   poll posts a redraw when the counter changes: up to ~30-60 frames/s.

Cost: users must run MIDISTOMP (or a fork) — a firmware flash, riskier than
installing a ZDL, though the bootloader stays untouched so update mode remains
(MIDISTOMP's approach). Best done with matujuice, against their issue #8.

## Stock firmware: what to probe

In order, each answering the question the next depends on:

| Probe | What it is | Tells us | Risk |
|---|---|---|---|
| **A. Redraw clock** — done | A knob's value text (GetString callback) shows the low digits of the DSP's cycle counter | **Result 2026-10-17: only on events.** Values stay frozen with hands off, change when the knob turns ([probe](../../src/hardware_probes/redraw/README.md)) | Low: no writes, no relocations |
| **B. Live sprite** | One knob uses a custom sprite (all frames the same); the effect rewrites its bytes from the audio code | Whether the firmware re-reads sprite bytes; if A showed a periodic refresh, a **mini scope in a knob box** (~44x16) on stock firmware | Medium: custom sprite styles are untested on our ZDLs (one style value froze the pedal before) |
| **C. Live cover** — done | The effect rewrites literal bytes of its own cover in RAM (designed so the RLE length can't change) | **Result 2026-10-17: re-read on every redraw.** The band flipped on screen the moment the effect was switched on/off; writes to the cover are allowed ([probe](../../src/hardware_probes/coverrw/README.md)) | Medium: writes to read-only-flagged memory |

A showed event-driven redraws, so on stock firmware a live picture needs
something that triggers redraws. Two routes stay open:

- **D. Trigger redraws from the effect — works (2026-10-18, [Blink](../../src/hardware_probes/blink/README.md)).** The audio code periodically posts the
  UI task's redraw event (MS-70CDR 2.10: `Event_post` at `0xC00CBF40`, event
  bit `0x40`; MIDISTOMP's addresses). Firmware-version specific, and calling
  OS code from the audio context has frozen MIDISTOMP builds before. If it
  works, value text animates on stock firmware; with C (cover re-read on each
  redraw) the cover itself could animate: a scope as an effect file.
- **Firmware patch** (MIDISTOMP route) as above.

So after A and C: an effect can change its own cover, and the screen shows it
on the next redraw; only the redraw trigger (D) is missing for animation.

Alexander Lim (Facebook, 2026-10-17) showed two MS-70CDR demos: a full-screen
"LMDS005 XY" scope (a live Lissajous ellipse) and a Chrome-style dinosaur game
played with the pedal's buttons, with scores and a scrolling ground. So full-
screen drawing, smooth animation and reading the buttons are all possible; how
(stock firmware calls or a firmware patch) is unknown, asked.

Do **not** call the edit handlers' UI postbox (`state[7]`) from audio code to
force redraws: it waits for the UI and would very likely deadlock
([build/ABI.md](../../build/ABI.md) 451-497).
