# NAMProf — where the full-rate NAM kernel's time goes

FXID 911, Delay, version 0.01. A diagnostic, not an effect; never ships.

## Running it

1. Install `NAMProf.ZDL` (+ `.png`) with Effect Manager. Close Effect Manager.
2. Make a patch with **NAMProf alone** — nothing before or after it. Leave the
   knobs at Input 44 / Output 27 / **Mix 100** (at Mix 0 the model never runs
   and it will measure forever).
3. Keep monitoring volume low. Start recording the pedal's **direct output**,
   then enable NAMProf.
4. About 2 seconds of normal NAM sound while it measures, then a steady stream
   of short beeps. Record **20 seconds** from when you enable it.
5. Save as WAV and run `python3 tools/decode_namprof.py recording.wav`.

If the pedal freezes **the moment you enable it**, the cache-register reads
were not permitted after all (they run on the first callback on purpose, so
that failure is immediate). Remove it in Effect Manager and report it.

## What it measures

- `period`: cycles per 8-sample callback — the real budget, and the clock speed.
- `min/avg/peak`: real cycles for the full-rate model (NAMTime's kernel).
  The emulator says 18,612 for the same code, and the C674x is statically
  scheduled, so **real minus emulated ≈ cycles stalled on memory** (plus any
  interrupts). Small gap → compute-bound → 16-bit SIMD is the lever. Large
  gap → memory-bound → layout/locality is the lever.
- Where the arena, the weights and the context actually live, and whether the
  arena's 16 MB region is cacheable (live MAR read).
- Live L1D/L2 cache config, to confirm the static reading from the firmware
  image: boot sets L1D 16 KB, L2 128 KB, and only DDR 0xC0000000-0xC0FFFFFF
  cacheable. The model's working set is ~140 KB — just over L2.

Read-only throughout: no register, clock or cache setting is written.

## Validation

- `validate.py`: host end-to-end — probe through every stage with a fake
  cycle counter (including a wrap), report rendered at 44.1 and 48 kHz with
  noise, all 14 words recovered exactly; arena guards and shuttle checked.
- The built ZDL runs in the Ziddle emulator through all stages with no
  unsupported instructions or faults (model stage ~20k emulated cycles, report
  418), and its played report decodes with valid sync and checksum.
- Relocations: 26 = NAMTime's 24 + one pair for the reported weights address,
  same types (ABS32, ABS_L16/H16) as the hardware-proven NAM builds.
