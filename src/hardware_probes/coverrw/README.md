# CoverRW (test C)

Does the MS-70CDR re-read an effect's cover picture on each redraw, or keep a
copy decoded when the effect was selected? The cover shows "TEST C" and a solid
band. Every time the effect is switched off or on, the audio code inverts the
band's bytes in its own cover in RAM (nearly solid black <-> nearly white with
dots). The compressed size never changes. Knob 1 ("Byte") shows the first band
byte as its value text: `FE` before a flip, `01` after one. Audio passes through.

    python3 src/hardware_probes/coverrw/build.py      # -> dist/CoverRW.ZDL (gitignored)

Needs the linker's `_<audio>_Pic` symbol (build/linker.py) for the cover's
runtime address. Emulator: `coverflip dist/CoverRW.ZDL 110` reads FE / 01 / FE
across on, off, on (tools/emulator/src/bin/coverflip.rs).

| On the pedal | Means |
|---|---|
| Band flips as soon as the screen redraws (switching on/off, or turning a knob) | The cover is re-read on redraw: a live cover works if redraws can be triggered |
| Band only changes after leaving and re-selecting the effect | A decoded copy is kept per selection |
| Band never changes, but Byte reads 01 after a flip | The write lands, but the screen uses its own copy |
| Byte stays FE | The write didn't land (memory protected) |
| Pedal freezes on the flip | Writes to the cover are trapped; remove CoverRW |

FXID 412 (unused).

**Result (MS-70CDR 2.10, 2026-10-17): re-read on redraw.** Switching the effect
on/off flips the band on screen immediately (the dark band disappears, and comes
back on the next flip), and Byte reads `01` while the band is white, `FE` while
it is dark. So the firmware decodes the cover from the effect's own
RAM on every redraw, and writes to it are allowed. A live cover works on stock
firmware wherever the screen gets redrawn; what's missing is a way to trigger
redraws without user input (test D).
