# MIDISTOMP transport block

How an effect follows MIDI clock under MIDISTOMP. Passed on by Luca Matturro
on 2026-10-22; his full spec is `docs/transport-block.md` in
[matujuice/zoom-ms-midistomp](https://github.com/matujuice/zoom-ms-midistomp)
(effect notes in `notes/transport-block-for-effects.md`). This file is our
summary. If they ever disagree, his spec wins.

## The block

Eight 32-bit words in RAM at `0x1181FF00`, present from power-on.

| Word | Meaning |
| --- | --- |
| 0 | Magic `0x5A4D5401` when MIDISTOMP is installed. Any other value means stock or older firmware: fall back to 120 BPM (or the effect's own Tempo knob). |
| 1 | Sequence counter. Odd means it is being written: read again. |
| 2 | Running: 1 after Start; 0 after Stop, or 0.5 s after the last clock. |
| 3 | Number of Starts received. |
| 4 | Clocks since Start. The first clock reads 1 and is the downbeat, so the position in 24ths of a beat is word 4 minus 1. |
| 5 | Tempo as BPM × 100. While clock runs, the clock's tempo; otherwise the patch TEMPO (tap, setting or patch load). |
| 6-7 | Reserved, always 0. |

Continue and Song Position are ignored.

## Rules for our effects

- Check the magic before reading anything else. Never write to the block.
- Read words 1 to 5 as one consistent snapshot: read word 1, the data, then
  word 1 again. Retry if it was odd or changed.
- While running, step on the clock count (word 4; a 16th is every 6 clocks),
  not on the tempo, so the effect stays locked without drift. Use the tempo
  word only to place events between clocks and to keep going after Stop.
- A change in word 3 (a new Start) resets the effect's bar position.
- The address, magic and layout are fixed. A layout change comes with a new
  magic, so an effect that checks the magic fails safe to its own tempo.

## Where we use it (planned)

- **Loop:** Tempo knob replaced by the clock while it runs. Quantized closes
  land on clock bars, and Start/Stop can start and stop the loop.
- **Hydra, Spiral:** delay times from the tempo word.

Not built yet. Test on a MIDISTOMP build, and on stock firmware, where the
magic is absent and every effect must behave exactly as now.
