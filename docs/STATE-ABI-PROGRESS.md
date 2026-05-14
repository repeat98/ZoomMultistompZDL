# State ABI Progress Log

Date: 2026-05-12

This log captures each concrete step toward the state model needed for 1:1
Airwindows ports. The rule is simple: if we learn something or build a probe,
write it down here before relying on it later.

## 2026-05-12: Current Blocker

State-heavy Airwindows effects cannot be 1:1 until the Zoom host state ABI is
mapped. `StereoChorus` alone needs two `int[65536]` delay lines plus multiple
history scalars. Stock ZDLs do not carry large writable ELF memory, and large
custom `.fardata` has frozen hardware before, so static delay arrays are not a
safe release strategy.

## 2026-05-12: PDF Findings

The TI manuals in `docs/` document the C6000 toolchain and startup rules, not
Zoom's private effect host. Useful constraints:

* Use `--mem_model:data=far` so custom globals do not rely on `B14`/`DP`.
* Reject near-data relocations such as `R_C6000_SBR_*` until DSBT/GOT support
  is deliberately implemented.
* Do not assume `.bss`, `.far`, `.cinit`, constructors, stack setup, or heap
  are initialized the way a normal C program would initialize them.
* Treat `malloc`/`calloc` as unavailable in ZDL audio code until proven.

## 2026-05-12: Stock Corpus Findings

The 830-file stock ZDL pass found no `PT_LOAD` segment where `memsz > filesz`.
Most `.fardata` sections are 24 bytes, only 80 files exceed that, and the
largest observed `.fardata` is 220 bytes. This supports the hypothesis that
large delay/reverb history is host-provided rather than embedded as writable
ELF data.

## 2026-05-12: Stock Audio Entry Clue

`build/disassemble_zdl.py` now extracts stock ELFs, runs TI `dis6x`, and
summarizes likely `ctx[...]` root reads near audio entry.

Early evidence:

| Effect | Extra fields beyond the known minimal map |
|---|---|
| `STCHO` / `CHORUS` | `ctx[2]`, `ctx[3]`, `ctx[13]`, `ctx[14]` |
| `DELAY` | `ctx[2]`, `ctx[3]` |
| `HALL` | `ctx[2]`, `ctx[3]` |

Working hypothesis: these are host-managed state/scratch/delay descriptors or
related runtime structures. They must be mapped on hardware before exact
Airwindows delay, chorus, tape, or reverb ports.

## 2026-05-12: Probe 1 - `CtxMap` v1

Added `src/airwindows/ctxmap/`, a hardware-only ABI mapper.

Purpose:

* Inspect `ctx[0..15]` one word at a time.
* Select a bit inside the word.
* Emit a square-wave tone if that bit is set.
* Never dereference the selected word.

Controls:

| Knob | Range | Meaning |
|---|---:|---|
| `Slot` | 0-15 | `ctx[]` index to inspect |
| `Bit` | 0-31 | bit inside the selected 32-bit word |
| `Level` | 0-100 | audible probe tone level |

Hardware test procedure:

1. Build `dist/CtxMap.ZDL` and load it on the pedal.
2. Feed silence into the pedal or record its output.
3. For each `Slot` from 0 to 15, sweep `Bit` from 0 to 31.
4. Record `1` when the tone is present and `0` when it is absent.
5. Reconstruct each `ctx[Slot]` word from the 32 bits.
6. Repeat after bypass, parameter edit, preset switch, and duplicate-instance
   tests.

Expected next evidence:

* Which fields are stable constants.
* Which fields look like addresses.
* Which fields change per instance or per preset.
* Whether suspected stock fields (`ctx[2]`, `ctx[3]`, `ctx[13]`, `ctx[14]`)
  are valid, stable, and per-instance.

Recording template:

| Condition | Slot | Bits 31..0 | Reconstructed word | Notes |
|---|---:|---|---|---|
| load, effect on | 0 | | | |
| load, effect on | 1 | | | |
| load, effect on | 2 | | | suspected stock state field |
| load, effect on | 3 | | | suspected stock state field |
| load, effect on | 13 | | | suspected stock modulation field |
| load, effect on | 14 | | | suspected stock modulation field |

Build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 448 bytes
* `.fardata`: 4 bytes (`gPhase` tone counter only)
* ZDL size: 5382 bytes
* Python syntax check: `python3 -B -m py_compile build/zdl.py
  build/disassemble_zdl.py src/airwindows/ctxmap/build.py build_all.py`

Hardware result:

* Interacting with the `Bit` parameter crashed the pedal.
* Most likely suspects are the object-defined inline-asm edit handler path or
  the 0-31 UI range for that parameter.
* Do not use this build for further mapping.

## 2026-05-12: Probe 1b - `CtxMap` Stock-Handler Low-Bit Build

Changed `CtxMap` to a two-control build:

| Knob | Range | Meaning |
|---|---:|---|
| `Slot` | 0-15 | `ctx[]` index to inspect |
| `Bit` | 0-15 | low-half bit inside the selected 32-bit word |

Changes from v1:

* Removed object-defined `ZOOM_EDIT_HANDLER` inline asm from `ctxmap.c`.
* Removed the `Level` control so both remaining controls use the stock-proven
  LineSel edit handlers from `linesel_handlers.bin`.
* Reduced `Bit` to 0-15 for the first hardware-safe pass.
* Fixed the probe tone level at `0.035f`.

Build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 384 bytes
* `.text`: 96 bytes
* `.fardata`: 4 bytes
* ZDL size: 4882 bytes

Next hardware check:

1. Load the rebuilt `dist/CtxMap.ZDL`.
2. First edit only `Slot` and confirm the pedal survives.
3. Then edit `Bit` slowly from 0 to 15.
4. If stable, map low 16 bits for `ctx[0]`, `ctx[1]`, `ctx[2]`, `ctx[3]`,
   `ctx[13]`, and `ctx[14]`.
5. Build a separate high-bit variant only after this low-bit build survives.

Hardware result:

* Sweeping all exposed bits across all slots did not crash.
* No audible output was heard.
* New suspects: `params[0]` may be zero/uninitialized for this probe, generated
  tone written only to `ctx[6]` may not reach the audible path, or the low
  16 bits of the selected words may all be zero/aligned.

## 2026-05-12: Probe 1c - `CtxMap` Baseline-Tone Build

Changed `CtxMap` again so the audio route is self-checking:

* Restored `Bit` range to 0-31 now that the stock-handler edit path survived.
* Removed dependence on `params[0]`; the probe tone is emitted regardless of
  the on/off multiplier.
* Emits a quiet baseline tone when the selected bit is `0`.
* Emits a louder tone when the selected bit is `1`.
* Writes the tone to both `ctx[5]` and `ctx[6]`.

Build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 448 bytes
* `.text`: 96 bytes
* `.fardata`: 4 bytes
* ZDL size: 4946 bytes

Next hardware check:

1. Load the rebuilt `dist/CtxMap.ZDL`.
2. With any `Slot`/`Bit`, confirm whether the quiet baseline tone is audible.
3. If the build is still silent, stop mapping bits and build an even simpler
   always-tone plugin with no param reads.
4. If the quiet tone is audible, sweep `Bit` 0-31 and record quiet vs loud.

Hardware result:

* The build produced a static tone for all slots and bits.
* The tone was still audible while the pedal reported the effect bypassed.
* This proves generated audio written to the current buffers can reach output,
  but it does not prove selected bits or parameters are changing.
* The bypass result means this diagnostic route is not suitable for judging
  normal effect bypass behavior.

## 2026-05-12: Probe 1d - Parameter Plumbing Check

Changed `CtxMap` temporarily from a `ctx[]` bit mapper into a parameter
audibility probe. It no longer reads `ctx[]`.

Expected behavior:

* `Slot` changes the amplitude of a lower square-wave tone.
* `Bit` changes the amplitude of a higher square-wave tone.

Interpretation:

* If the sound changes when either knob moves, the two stock LineSel edit
  handlers are updating `params[5]` and `params[6]`.
* If the sound remains static, the next blocker is descriptor/handler/param
  plumbing, and `ctx[]` mapping must wait.

Build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 608 bytes
* `.text`: 64 bytes
* `.fardata`: 4 bytes
* ZDL size: 5074 bytes

Hardware result:

* The pedal crashed on startup with this build.
* Do not use this variant again.
* The likely differences from the previous hardware-surviving build were:
  generated two-tone audio, different optimized `.audio` shape, and total
  `.text` layout reaching `0x800` bytes instead of `0x780`.
* Rolled `src/airwindows/ctxmap/` back to the previous baseline-tone behavior
  so `dist/CtxMap.ZDL` is again a recovery/survival build, not the crashing
  param-audibility variant.

Recovery build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 448 bytes
* `.text`: 96 bytes
* `.fardata`: 4 bytes
* ZDL size: 4946 bytes

## 2026-05-12: Probe 2 - `ParamTap`

Added `src/airwindows/paramtap/` as a separate effect ID so `CtxMap` can stay
on its last hardware-surviving build.

Purpose:

* Prove whether two stock LineSel edit handlers update `params[5]` and
  `params[6]`.
* Avoid generated oscillator audio.
* Avoid `.fardata`.
* Avoid unknown `ctx[]` reads.

Behavior:

* Feed guitar/input signal through the pedal.
* `TapA` controls gain for the first 8-float half of the block.
* `TapB` controls gain for the second 8-float half of the block.

Interpretation:

* If `TapA`/`TapB` change the level, parameter plumbing is working and the
  static `CtxMap` tone is probably caused by the selected `ctx` words/bit
  evidence or by how we audibly encoded it.
* If they do not change level, pause `ctx` mapping and fix descriptor/edit
  handler/param writes first.
* If it crashes, the next probe should be `audio_nop=true` for `ParamTap` to
  isolate descriptor/UI load from audio execution.

Build result:

* Command: `python3 -B build_all.py paramtap`
* Output: `dist/ParamTap.ZDL`
* `.audio`: 416 bytes
* `.text`: 0 bytes
* `.fardata`: 0 bytes
* ZDL size: 4842 bytes

Hardware result:

* Startup survived.
* Both parameters changed loudness.
* `TapA` controlled the left channel and `TapB` controlled the right channel.
* Conclusion: the first two stock LineSel edit handlers do update
  `params[5]` and `params[6]` in our diagnostic effects.

## 2026-05-12: Probe 3 - `CtxGate`

Added `src/airwindows/ctxgate/`, a separate input-based `ctx[]` bit mapper.

Purpose:

* Keep `CtxMap` as the recovery/survival build.
* Reuse the parameter path proven by `ParamTap`.
* Avoid generated oscillator audio.
* Avoid `.fardata`.
* Read `ctx[Slot]` as one raw 32-bit word without dereferencing it.

Behavior:

* Feed guitar/input signal through the pedal.
* `Slot` selects `ctx[0..15]`.
* `Bit` selects bit `0..31`.
* Selected bit `0` -> quiet pass-through gain (`0.10f`).
* Selected bit `1` -> loud pass-through gain (`1.25f`).

Hardware test procedure:

1. Load `dist/CtxGate.ZDL`.
2. Confirm startup survives.
3. Feed a steady input signal.
4. Sweep `Slot` and `Bit`.
5. Record quiet as `0` and loud as `1`.
6. Prioritize `ctx[2]`, `ctx[3]`, `ctx[13]`, and `ctx[14]`, because stock
   stateful effects read those fields early.

Recording template:

| Condition | Slot | Bits 31..0 | Reconstructed word | Notes |
|---|---:|---|---|---|
| input-gated, effect on | 2 | | | suspected stock state field |
| input-gated, effect on | 3 | | | suspected stock state field |
| input-gated, effect on | 13 | | | suspected stock modulation field |
| input-gated, effect on | 14 | | | suspected stock modulation field |

Build result:

* Command: `python3 -B build_all.py ctxgate`
* Output: `dist/CtxGate.ZDL`
* `.audio`: 288 bytes
* `.text`: 96 bytes
* `.fardata`: 0 bytes
* ZDL size: 4790 bytes

Hardware result:

* Startup survived.
* Sweeping all bits across all slots did not crash.
* Audio passed through across all settings; no clear quiet/loud bit encoding
  was heard.
* Because `ParamTap` proved the same two parameters can control gain, the next
  suspect is the selector implementation in `CtxGate`, especially the
  float-to-int conversion used to turn raw knob values into `slot` and `bit`.

## 2026-05-12: Probe 3b - `CtxGate` Threshold Selector

Changed `CtxGate` to keep the same input-gated behavior but remove
float-to-int casts from the slot/bit selector path.

Changes:

* Removed `zoom_params.h` from this probe.
* Replaced `raw -> normalized float -> int` conversion with explicit raw-float
  threshold ladders.
* Kept the selected `ctx[Slot]` word read-only and non-dereferenced.
* Kept `.fardata` at zero.

Interpretation:

* If this build now changes quiet/loud while sweeping, the previous
  float-to-int selector path was the issue.
* If it still just passes audio through, the next likely issue is that adding
  to `ctx[6]` is being masked by an existing dry/output path; the follow-up
  should encode bits by channel imbalance or by modifying `ctx[5]` in-place.

Build result:

* Command: `python3 -B build_all.py ctxgate`
* Output: `dist/CtxGate.ZDL`
* `.audio`: 1408 bytes
* `.text`: 0 bytes
* `.fardata`: 0 bytes
* ZDL size: 5814 bytes

Hardware result:

* Startup survived.
* Sweeping bits across different slots produced many audible volume changes.
* Sweeping bit `0` across slots did not change the sound.
* Conclusion: `CtxGate` is now receiving parameter changes and reading some
  `ctx[]`-dependent signal, but the quiet/loud gain encoding is too ambiguous
  to reconstruct words reliably. The pedal's existing dry/output path likely
  masks the intended binary distinction.

## 2026-05-12: Probe 3c - `CtxGate` Stereo Encoder

Changed `CtxGate` to encode the selected bit as stereo balance rather than
plain volume.

Behavior:

* Selected bit `0` -> stronger left-side pass-through.
* Selected bit `1` -> stronger right-side pass-through.
* Still uses the threshold selector from Probe 3b.
* Still does not dereference the selected `ctx[]` word.
* Still uses no `.fardata`.

Interpretation:

* Record or monitor in stereo.
* Classify left-leaning settings as `0`.
* Classify right-leaning settings as `1`.
* If bit `0` remains unchanged across slots, document it as a likely constant
  low bit rather than spending time on it.

Build result:

* Command: `python3 -B build_all.py ctxgate`
* Output: `dist/CtxGate.ZDL`
* `.audio`: 1568 bytes
* `.text`: 0 bytes
* `.fardata`: 0 bytes
* ZDL size: 5974 bytes

Hardware result:

* Startup survived.
* The probe now audibly pans the signal.
* Conclusion: stereo balance is a usable binary observation channel for
  selected `ctx[Slot].Bit` values. Use left/right classification instead of
  raw volume changes for the next mapping pass.

Next mapping target:

* Sweep bits `0..31` for `ctx[2]`, `ctx[3]`, `ctx[13]`, and `ctx[14]`.
* Record left-leaning as `0` and right-leaning as `1`.
* If a bit produces no clear pan difference, mark it as `?` instead of
  guessing.

Observed mapping data:

Assumption for provisional hex: the strings below are written in sweep order,
with the first character corresponding to bit `0` and the last character
corresponding to bit `31`.

| Slot | Sweep bits 0..31 | Provisional word | Notes |
|---:|---|---:|---|
| `ctx[2]` | position-dependent; see chain-position check below | `0xfffff1e3` or `0xfffff1eb` | stock state/scratch candidate |
| `ctx[3]` | position-dependent; see chain-position check below | `0x00003e3b` or `0x00003e39` | stock state/scratch candidate |
| `ctx[13]` | `11001110011111000000000000000000` | `0x00003e73` | stock modulation/state candidate |
| `ctx[14]` | `11001110011111000000000000000000` | `0x00003e73` | same observed value as `ctx[13]` |

`ctx[2]` first looked inconsistent, but a chain-position check now suggests
that the high-bit-heavy readings are real and depend on the physical FX slot.
The isolated `0x00000e1b` reading is no longer trusted until reproduced.

`ctx[3]` first looked inconsistent, but a chain-position check now suggests
that the value depends on the physical FX slot rather than being a
transcription error.

If the bit strings were instead written most-significant-bit first, the words
would be `0xc78fffff`, `0x9c7c0000`, and `0xce7c0000`. The next capture should
explicitly confirm whether the first typed character is bit `0`.

Duplicate-instance check:

| Condition | Slot | Sweep bits 0..31 | Provisional word | Notes |
|---|---:|---|---:|---|
| Duplicate `CtxGate` in second FX slot | `ctx[3]` | `10011100011111000000000000000000` | `0x00003e39` | matches repeat single-instance sweep |
| Same duplicate-instance condition | `ctx[13]` | `11001110011111000000000000000000` | `0x00003e73` | unchanged |

Chain-position check:

| Condition | Slot | Sweep bits 0..31 | Provisional word | Notes |
|---|---:|---|---:|---|
| One `CtxGate`, physical FX slot 1 | `ctx[2]` | `11000111100011111111111111111111` | `0xfffff1e3` | differs by bit 3 |
| One `CtxGate`, physical FX slot 2, no effect in slot 1 | `ctx[2]` | `11010111100011111111111111111111` | `0xfffff1eb` | differs by bit 3 |
| One `CtxGate`, physical FX slot 1 | `ctx[3]` | `11011100011111000000000000000000` | `0x00003e3b` | differs by bit 1 |
| One `CtxGate`, physical FX slot 2, no effect in slot 1 | `ctx[3]` | `10011100011111000000000000000000` | `0x00003e39` | differs by bit 1 |
| One `CtxGate`, physical FX slot 1 | `ctx[13]` | `11001110011111000000000000000000` | `0x00003e73` | unchanged across positions |
| One `CtxGate`, physical FX slot 2, no effect in slot 1 | `ctx[13]` | `11001110011111000000000000000000` | `0x00003e73` | unchanged across positions |
| One `CtxGate`, physical FX slot 2, no effect in slot 1 | `ctx[14]` | `11001110011111000000000000000000` | `0x00003e73` | matches `ctx[13]` |

Interpretation so far:

* `ctx[13]` and `ctx[14]` matched exactly in this capture.
* `ctx[2]` appears to encode chain position or a chain-position-related flag:
  physical FX slot 1 produced `0xfffff1e3`, while physical FX slot 2 produced
  `0xfffff1eb`.
* `ctx[3]` appears to encode chain position or a chain-position-related flag:
  physical FX slot 1 produced `0x00003e3b`, while physical FX slot 2 produced
  `0x00003e39`.
* `ctx[13]` stayed fixed at `0x00003e73` across physical FX slot 1 and 2 in
  this test.
* `ctx[14]` also read `0x00003e73` in physical FX slot 2, matching `ctx[13]`
  and the earlier `ctx[14]` sweep.
* The observed values are small if interpreted as bit-0-first words, so they
  do not yet look like direct memory pointers. They may be flags, indexes,
  compact descriptors, or the bit order may still need confirmation.

## Next Probe

## 2026-05-12: Probe 4 - `CtxNib`

Added `src/airwindows/ctxnib/`, a nibble mapper to reduce manual sweep errors.

Purpose:

* Keep the proven stereo/input observation channel from `CtxGate`.
* Read a whole 4-bit nibble from `ctx[Slot]` at once.
* Avoid 32 separate bit-position edits per slot.
* Avoid dereferencing the selected `ctx[]` word.

Behavior:

* `Slot` selects `ctx[0..15]`.
* `Nib` selects one nibble:
  * `Nib 0` = bits `0..3`
  * `Nib 1` = bits `4..7`
  * ...
  * `Nib 7` = bits `28..31`
* The audio pattern repeats:
  * sync: loud center
  * bit 0: left = `0`, right = `1`
  * bit 1: left = `0`, right = `1`
  * bit 2: left = `0`, right = `1`
  * bit 3: left = `0`, right = `1`
  * gap: quiet center

Test procedure:

1. Load `dist/CtxNib.ZDL`.
2. Feed a steady input signal and monitor/record stereo.
3. Set `Slot` to a target, for example `3`.
4. Set `Nib` to `0`.
5. After the loud center sync, write the next four pan decisions as a nibble
   string, left=`0`, right=`1`.
6. Repeat for `Nib 1..7`.

Build result:

* Command: `python3 -B build_all.py ctxnib`
* Output: `dist/CtxNib.ZDL`
* `.audio`: 608 bytes
* `.text`: 448 bytes
* `.fardata`: 4 bytes
* ZDL size: 5466 bytes

Hardware/operator result:

* Rejected as a worse workflow than `CtxGate`.
* Keep the build around only as an optional probe; do not use it as the main
  mapping workflow.

Next after `CtxNib`:

If `CtxNib` confirms stable compact words, the next probe is a read-only
dereference mapper only if a candidate field looks pointer-like. If values stay
small, first map how these compact fields vary by FX slot, preset, bypass, and
duplicate instance.

## 2026-05-12: Stock Assembly Pivot

Manual sweeping has gone far enough for now. Stock ZDL disassembly gives a
stronger lead than more hand sweeps.

Added `build/trace_ctx_audio.py`, a lightweight `dis6x` text tracer for
`.audio` sections. It tracks direct `ctx[]` loads and later memory accesses
through the loaded registers. It is a triage tool, not a decompiler.

Command used:

```bash
python3 -B build/disassemble_zdl.py \
  stock_zdls/MS-70CDR_STCHO.ZDL \
  stock_zdls/MS-70CDR_DELAY.ZDL \
  stock_zdls/MS-70CDR_HALL.ZDL \
  stock_zdls/MS-70CDR_MODREV.ZDL \
  stock_zdls/MS-70CDR_TAPEECHO.ZDL \
  --out-dir /tmp/zoom-stock-state-trace

python3 -B build/trace_ctx_audio.py \
  /tmp/zoom-stock-state-trace/MS-70CDR_STCHO.ZDL.asm \
  /tmp/zoom-stock-state-trace/MS-70CDR_DELAY.ZDL.asm \
  /tmp/zoom-stock-state-trace/MS-70CDR_HALL.ZDL.asm
```

Key stock findings:

| Stock effect | `ctx[2]` use | `ctx[3]` use | `ctx[13]` / `ctx[14]` use |
|---|---|---|---|
| `STCHO` | base pointer; reads/writes fields including `[0]`, `[1]`, `[3]`, `[5]` | base pointer; repeated reads from `[0]`, `[1]`, `[2]` | `ctx[13]` dereferenced and written through; `ctx[14]` dereferenced/read |
| `DELAY` | base pointer; derived struct at `ctx[2] + 0x10`, fields read/written | base pointer; fields `[0]`, `[1]`, `[2]` read | not used in this audio entry |
| `HALL` | base pointer; derived struct and state fields read/written | base pointer; fields `[0]`, `[1]`, `[2]` read | not used in this audio entry |
| `TAPEECHO` | base pointer; fields `[0]`, `[2]`, `[3]` read/written | base pointer; fields `[0]`, `[1]`, `[2]` read | not used in this audio entry |

Interpretation:

* Stock stateful effects treat `ctx[2]` and `ctx[3]` as pointers to runtime
  structs, not merely scalar flags.
* `STCHO` additionally treats `ctx[13]` and `ctx[14]` as pointer-like fields,
  possibly a host scratch or transfer pair.
* Our manual bit sweeps are still useful as behavioral probes, but they are not
  enough to recover actual addresses. The next target is firmware code that
  constructs the `ctx[]` array before calling an effect's `.audio` function.

Next firmware target:

* Search firmware disassembly for the call path that stores into callback
  context slots `[2]`, `[3]`, `[13]`, and `[14]`.
* Avoid more pedal sweeping until that call path suggests a specific probe.

## 2026-05-12: Firmware Call-Path Triage

Added `build/find_firmware_ctx_call_candidates.py`, a text scanner for
`main_os.dis`. It finds indirect branches/calls, then reports nearby stores to
small struct offsets on the same base register. The goal is to find code that
constructs a ZDL audio call frame or a stock-style state descriptor without
hand-scanning the full firmware listing.

Command used:

```bash
python3 -B build/find_firmware_ctx_call_candidates.py \
  firmware/extracted/main_os.dis \
  --min-score 50 --max-candidates 30 --limit 10
```

Current interpretation:

* `c00d3340..c00d3518` is almost certainly not the ZDL audio callback path.
  It saves/restores CPU state (`CSR`, `AMR`, `IRP`, `ILC`, `RILC`, `SSR`,
  `TSR`, `ITSR`, `GPLYA`, `GPLYB`) around an indirect branch at `c00d3404`.
  Treat it as an interrupt/exception/context-save trampoline unless disproven.
* `c00de7a0..c00de818` is also likely a low-level context/coroutine switch.
  It swaps `B15`, saves/restores preserved registers, then branches through a
  stored return/function pointer. It is useful firmware context, but probably
  not the effect audio frame builder.
* `c00dbae0` behaves like `memset(dest=A4, byte=B4, len=A6)`. This makes
  state-initializer candidates much easier to read.
* `c00de2a0..c00de32c` is the best state-descriptor lead so far:
  * loads a count from global `0xc00e:d054`;
  * iterates descriptors returned by `c00e1100(index)`;
  * reads `descriptor[14]` as a signed halfword;
  * clears `descriptor[2]` for `descriptor[14] << 5` bytes via `c00dbae0`;
  * resets `descriptor[3] = descriptor[2]`;
  * resets `descriptor[5] = 0`, `descriptor[6] = 1`, and
    halfword `descriptor[16] = 1`.
* `c00e1100` appears to be an indexed descriptor accessor for a table rooted
  near `0xc00e:e108`.
* `c00e1080` checks `descriptor[2]`, reads `descriptor[14]`, and branches to
  another descriptor helper (`c00e1180`) when the backing pointer exists.
* `c00e1140` calls the `c00d5a60` helper after zeroing argument registers,
  which makes `c00d5a60` look like a descriptor use/reset helper rather than
  an isolated random indirect-call site.
* `c00d1e40..c00d204c` and `c00d5a60..c00d5bd8` are high-scoring indirect-call
  candidates. They manipulate structs with fields `[2]`, `[3]`, `[4]`,
  `[5]`, `[6]`, `[7]` and branch indirectly. These may be descriptor
  read/write helpers or event/callback wrappers; they are not yet proven to be
  the actual ZDL `.audio` caller.

Why this matters:

Stock effects treat `ctx[2]` and `ctx[3]` as pointers to runtime structs. The
`c00de2a0` descriptor reset routine is the first firmware evidence of a
host-managed memory block with pointer, cursor, size-in-32-byte-units, and
reset flags. That is the kind of storage model needed for 1:1 Airwindows ports,
but we still need to connect this descriptor family to one or more audio
`ctx[]` slots.

Next firmware steps:

1. Trace references to the `0xc00e:d054` descriptor count and `0xc00e:e108`
   descriptor table.
2. Trace `c00de200`, which appears in the same descriptor-control neighborhood
   and may allocate or attach these backing blocks.
3. Trace callers of `c00de2a0` and the high-scoring `c00d1e40` /
   `c00d5a60` helpers.
4. Cross-check stock `.audio` field accesses against the descriptor shape:
   pointer fields `[2]` / `[3]`, cursor-like fields, and length field `[14]`.
5. Only after that, build a tiny read/write persistence probe against the most
   plausible `ctx[]` slot; do not return to manual bit sweeping.

## 2026-05-12: Derived Stock State Shapes

Added `build/trace_ctx_structs.py`, a second stock-audio tracer. Unlike
`trace_ctx_audio.py`, it follows simple derived bases such as `ctx[2] + 0x10`
and `ctx[2] + 0x18`, then summarizes which fields are read/written through
each base.

Command used:

```bash
python3 -B build/trace_ctx_structs.py \
  /tmp/zoom-stock-state-trace/MS-70CDR_STCHO.ZDL.asm \
  /tmp/zoom-stock-state-trace/MS-70CDR_DELAY.ZDL.asm \
  /tmp/zoom-stock-state-trace/MS-70CDR_TAPEECHO.ZDL.asm \
  --limit 2
```

Important correction:

`c00de200` is now downgraded as a state-storage lead. It has many callers, and
sampled call sites pass small source-location/error constants such as
`0x0135`, `0x02f3`, and `0x022e` along with feature flags. Treat it as a
common assert/log/diagnostic dispatcher unless a later trace proves otherwise.

Current stock-audio field shapes:

| Stock effect | `ctx[2]` direct fields | derived state block | `ctx[3]` fields |
|---|---:|---:|---:|
| `STCHO` | `[0]`, `[1]`, `[3]`, `[5]` | `ctx[2] + 0x18`, fields `[0..7]` | `[0]`, `[1]`, `[2]` |
| `DELAY` | `[0]`, `[1]`, `[2]`, `[3]` | `ctx[2] + 0x10`, fields `[0..12]` | `[0]`, `[1]`, `[2]` |
| `TAPEECHO` | `[0]`, `[2]`, `[3]` | `ctx[2] + 0x18`, fields `[0..14]`, `[16]`, `[17]`, `[18]` | `[0]`, `[1]`, `[2]` |

Interpretation:

* `ctx[2]` is very likely a host-provided per-instance state header, not just
  a scalar flag.
* Several stock effects derive their larger mutable state area from `ctx[2]`
  using a fixed offset. `DELAY` uses `+0x10`; `STCHO` and `TAPEECHO` use
  `+0x18`.
* `TAPEECHO` is now the strongest stock template for a larger persistent block:
  it writes back many derived fields at the end of the audio call, including
  `[14]` and `[16]`.
* `ctx[3]` still looks like a separate three-field descriptor used for indexed
  addressing or wrap/bounds handling. Stock code reads from it but does not
  write through it in these inspected audio entries.
* `ctx[13]` / `ctx[14]` are still special for modulation-style effects. In
  `STCHO`, both are pointer-like one-word cells; in `MODREV`, `ctx[13]` is
  dereferenced and written through while `ctx[14]` is read.

Next concrete probe:

Build a minimal persistence probe that uses the stock pattern conservatively:
read/write only the first few words of `ctx[2] + 0x10` or `ctx[2] + 0x18`,
encode whether the value persists across audio callbacks as stereo panning,
and avoid touching `ctx[3]`, `ctx[13]`, or `ctx[14]` until the `ctx[2]` state
block is proven on custom ZDLs.

## 2026-05-12: Probe 5 - `StatePing`

Added `src/airwindows/stateping/`, a default-safe persistence probe for the
stock `ctx[2]` derived-block pattern.

Purpose:

* Test whether custom ZDLs get the same writable state block shape that stock
  delay/chorus effects use.
* Avoid startup crashes by defaulting to `Base=0`, which does not dereference
  `ctx[2]`.
* Avoid broad manual bit sweeps. This is a direct yes/no persistence probe.

Behavior:

* `Arm10=0`, `Arm18=0`: pass-through, no `ctx[2]` dereference.
* `Arm10=1`: test word 0 at `ctx[2] + 0x10`, matching stock `DELAY`.
* `Arm18=1`: test word 0 at `ctx[2] + 0x18`, matching stock `STCHO` /
  `TAPEECHO`. `Arm18` takes priority if both switches are on.
* When armed, the probe increments the selected word once per audio callback
  and uses bit `0x20` of the counter to pan/weight the input:
  * bit clear: stronger left;
  * bit set: stronger right.

Expected hardware interpretation:

* Loads with both arms off: descriptor/UI/audio path is safe.
* `Arm10=1` creates a repeated left/right wobble: custom ZDL can
  write persistent state at `ctx[2] + 0x10`.
* `Arm18=1` creates a repeated left/right wobble: custom ZDL can
  write persistent state at `ctx[2] + 0x18`.
* It stays fixed left/right or does not wobble: the word is not persisting, or
  host code rewrites it every callback.
* It crashes only after enabling `Arm10` or `Arm18`: that derived pointer is
  not safe for custom ZDLs, despite stock effects using that shape.

Build result:

* Command: `python3 -B build_all.py stateping`
* Output: `dist/StatePing.ZDL`
* `.audio`: 512 bytes
* `.text`: 0 bytes
* `.fardata`: 0 bytes
* ZDL size: 4938 bytes

Hardware/operator result:

* No crash with both arms off, either arm on, or both arms on.
* No audible wobble in any state.

Follow-up fix:

The first `StatePing` build treated the arm controls as full normalized
`0.0/1.0` switches and used a `>= 0.5f` threshold. That is probably wrong for
our stock-derived edit handlers: `ParamTap` showed parameter writes are small
raw floats. Lowered the arm threshold to `>= 0.001f` so switch/knob writes above
zero actually arm the probe.

Retest result after threshold fix:

* `Arm10=1` produces stereo wobble.
* `Arm18=1` produces stereo wobble.
* Both arms on also produces stereo wobble. In this build `Arm18` has priority,
  so that confirms the `ctx[2] + 0x18` path still works when both switches are
  nonzero.
* No crash reported.

Conclusion:

Custom ZDL audio callbacks can write persistent per-callback state through the
stock `ctx[2]` derived-block pattern, at least at word 0 of both `ctx[2] +
0x10` and `ctx[2] + 0x18`. This is the first hardware proof that a 1:1
stateful Airwindows port does not have to keep all state in `.fardata`.

Immediate next questions:

1. How many words are safe in the derived block?
2. Are the blocks per effect instance, or shared across duplicate instances?
3. Does bypass/preset switching reset this block the same way stock effects do?
4. Can we influence the block size from ZDL metadata, or is the custom block a
   fixed host allocation?

Follow-up build:

Extended `StatePing` with a `Word` knob (`0..31`) so the same probe can test
state depth. The two arms still select the derived block:

* `Arm10=1`: write/increment `ctx[2] + 0x10 + Word*4`.
* `Arm18=1`: write/increment `ctx[2] + 0x18 + Word*4`.

Suggested next hardware points:

* `Arm10=1`, `Word=12` because stock `DELAY` uses through derived word 12.
* `Arm18=1`, `Word=18` because stock `TAPEECHO` uses through derived word 18.
* If those work, try `Word=19`, then `Word=31` cautiously to find whether the
  custom allocation extends beyond the stock-observed range.

Build result for word-selector version:

* Command: `python3 -B build_all.py stateping`
* Output: `dist/StatePing.ZDL`
* `.audio`: 576 bytes
* `.text`: 768 bytes
* `.fardata`: 0 bytes
* ZDL size: 5986 bytes

Hardware/operator result:

* Interacting with `Word=31` froze/crashed the pedal.

Follow-up fix:

`Word=31` is now marked unsafe. Capped `StatePing`'s `Word` parameter at 19
and removed selector cases above 19 so the next build cannot casually hit the
known-freezing offset. Keep future depth tests near stock-observed boundaries:
`Word=12`, `Word=18`, then `Word=19`.

Build result for capped version:

* Command: `python3 -B build_all.py stateping`
* Output: `dist/StatePing.ZDL`
* `.audio`: 576 bytes
* `.text`: 384 bytes
* `.fardata`: 0 bytes
* ZDL size: 5602 bytes

Hardware/operator result:

* Interacting with the `Word` parameter still froze the pedal and produced a
  high-pitched sine/square-like tone.
* This makes the interactive depth selector itself unsafe on hardware, not just
  the previously tested `Word=31` endpoint.

Follow-up fix:

Removed the interactive `Word` parameter from `StatePing`. Depth probes are now
separate fixed-word ZDL variants that only expose the previously proven
`Arm10` and `Arm18` switches:

* `StatePing.ZDL`: fixed word 0.
* `StateP12.ZDL`: fixed word 12.
* `StateP18.ZDL`: fixed word 18.
* `StateP19.ZDL`: fixed word 19.

For each fixed variant:

* `Arm10=1` writes/increments `ctx[2] + 0x10 + fixed_word*4`.
* `Arm18=1` writes/increments `ctx[2] + 0x18 + fixed_word*4`.
* `Arm18` still takes priority when both switches are on.

Testing guidance:

Do not continue hardware testing with any `StatePing` build that still has a
`Word` parameter. Use the fixed-word variants only. Test `StateP12` first, then
`StateP18`, then `StateP19` cautiously if the earlier variants load and wobble.

Build result for fixed-word variant set:

* Command: `python3 -B build_all.py stateping`
* Outputs:
  * `dist/StatePing.ZDL`: fixed word 0.
  * `dist/StateP12.ZDL`: fixed word 12.
  * `dist/StateP18.ZDL`: fixed word 18.
  * `dist/StateP19.ZDL`: fixed word 19.
* Each output:
  * `.audio`: 512 bytes.
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * ZDL size: 4914 bytes.

Hardware/operator result:

All fixed-word variants loaded and produced stereo wobble from either derived
base:

| Variant | Fixed word | `Arm10` result | `Arm18` result |
|---|---:|---|---|
| `StatePing` / `StateP0` | 0 | wobble | wobble |
| `StateP12` | 12 | wobble | wobble |
| `StateP18` | 18 | wobble | wobble |
| `StateP19` | 19 | wobble | wobble |

Conclusion:

Custom ZDLs can safely write at least words 0, 12, 18, and 19 through both
`ctx[2] + 0x10` and `ctx[2] + 0x18`. This covers the highest stock-observed
derived word plus one extra word. It does not solve large Airwindows delay-line
storage, but it gives us a proven host-state area for per-instance scalar state
and for building safer follow-up probes.

## 2026-05-12: Probe 5 - `StateIso`

Added `src/airwindows/stateiso/`, a hardware-only instance-isolation probe.

Purpose:

* Test whether the proven `ctx[2] + 0x18` block is private per effect instance.
* Avoid more bit/word sweeping.
* Use fixed variants and one safe arm switch only.

Behavior:

* `Arm=0`: pass-through, no `ctx[2]` dereference.
* `Arm=1`: uses `ctx[2] + 0x18`.
* Word 18 is a phase counter for audible reporting.
* Word 19 stores a variant-specific magic stamp.
* `StateIsoA` writes `0x13579BDF`.
* `StateIsoB` writes `0x2468ACE0`.
* If a variant sees any nonzero stamp other than its own, it reports a foreign
  stamp as stereo wobble.

Testing guidance:

1. Load `StateIsoA` alone and turn `Arm` on. It may make a brief transition
   sound, then it should settle to centered pass-through.
2. Load `StateIsoA` in one effect slot and `StateIsoB` in another. Turn both
   arms on.
3. If the host block is per instance, the chain should stay centered/pass-through
   after startup.
4. If both slots share the same host block, the two variants should keep seeing
   each other's stamps and produce continuous stereo wobble.

Build result:

* Command: `python3 -B build_all.py stateiso`
* Outputs:
  * `dist/StateIsoA.ZDL`
  * `dist/StateIsoB.ZDL`
* Each output:
  * `.audio`: 512 bytes.
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * ZDL size: 4782 bytes.

Hardware/operator result:

* Flashing both `StateIsoA` and `StateIsoB` made the pedal crash on startup.
* Flashing either effect by itself allowed the pedal to boot.
* A single isolated `StateIso` loads, passes audio, and changing `Arm` does not
  audibly affect the sound.

Interpretation:

The single-effect behavior is consistent with the probe design: it only makes
an audible wobble when it sees a foreign stamp, so one isolated variant should
settle to normal pass-through. The startup crash with both variants installed
looks like an install-time loader/package conflict rather than an instance-state
sharing result. First suspect: both variants exported the same audio callback
symbol, `Fx_FLT_StateIso`.

Follow-up fix:

Rebuilt the two variants with unique exported audio callback names:

* `StateIsoA`: `Fx_FLT_StateIsoA`.
* `StateIsoB`: `Fx_FLT_StateIsoB`.

Keep the same effect IDs and DSP behavior so the next hardware test isolates
whether the duplicate callback symbol was the startup-crash trigger.

Build result for unique-symbol version:

* Command: `python3 -B build_all.py stateiso`
* Outputs:
  * `dist/StateIsoA.ZDL`
  * `dist/StateIsoB.ZDL`
* Each output:
  * `.audio`: 512 bytes.
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * ZDL size: 4786 bytes.
* String check confirms the exported callback/edit/init/onf symbols are
  variant-specific.

Hardware/operator result:

* The pedal still does not boot when both `StateIsoA` and `StateIsoB` are
  flashed, even after giving the variants unique callback/edit/init/onf symbols.

Interpretation:

The duplicate-symbol hypothesis is ruled out. Two separately installed
`StateIso` diagnostic ZDLs appear to trigger a loader/package conflict before
audio-instance testing can begin. Do not flash the A/B pair for further tests.

Follow-up fix:

Replaced the A/B pair with a single `StateIso.ZDL` that can be duplicated in two
effect slots. It has two safe stock-handler controls:

* `Arm`: `0` = pass-through, `1` = stamp/test `ctx[2] + 0x18`.
* `Role`: `0` = write role-A magic `0x13579BDF`, `1` = write role-B magic
  `0x2468ACE0`.

New testing guidance:

1. Flash only `StateIso.ZDL`; remove `StateIsoA.ZDL` and `StateIsoB.ZDL` from
   the pedal.
2. Confirm the pedal boots with the single installed effect.
3. Add one `StateIso` instance, set `Arm=1`, leave `Role=0`. It should pass
   audio without continuous wobble.
4. Add two `StateIso` instances in one patch. Set slot 1 to `Arm=1, Role=0`;
   set slot 2 to `Arm=1, Role=1`.
5. Continuous wobble means the two instances share the same host state block.
   Centered/pass-through means the block is likely per instance.

Build result for single-effect duplicate-instance version:

* Command: `python3 -B build_all.py stateiso`
* Output: `dist/StateIso.ZDL`
* `.audio`: 544 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* ZDL size: 4958 bytes.

Hardware/operator result:

* Two `StateIso` instances loaded in FX slot 1 and FX slot 2 did not produce
  wobble in either `Role` switch position.

Interpretation:

This is the expected result for isolated per-instance host state: slot 1 and
slot 2 do not see each other's word-19 stamp at `ctx[2] + 0x18`. Based on the
earlier successful two-control probes, the working conclusion is that the
`ctx[2] + 0x18` derived block is per effect instance, at least for the tested
words. That gives custom ZDLs a small, proven per-instance state region.

Remaining caveat:

This does not prove the block is large enough for Airwindows delay lines, and
it assumes the `Role` switch is reaching the second parameter slot correctly.
The next useful probe should use the same host-state words as actual audio
history so the state mechanism is tested as DSP memory, not just counters and
magic stamps.

## 2026-05-13: Probe 7 - `StateComb`

Added `src/airwindows/statecomb/`, a tiny audio-history probe.

Purpose:

* Test whether the proven `ctx[2] + 0x18` words behave like normal DSP history.
* Use actual sample history instead of counters/magic stamps.
* Stay within the proven safe word range.

Behavior:

* `Arm=0`: pass-through, no `ctx[2]` dereference.
* `Arm=1`: uses `ctx[2] + 0x18`.
* Words `0..15` store a mono 16-sample feedback comb ring.
* Word `18` stores the ring index.
* `Mix` controls the delayed comb contribution.

Expected hardware interpretation:

* If the host state persists across audio callbacks, `Arm=1` should color the
  sound with a small comb/filter-like effect.
* If the host state is reset every callback, `Arm=1` should mostly behave like
  pass-through or only create a very weak transient.
* This is not a production delay and not an Airwindows port. It is only a
  state-memory sanity check.

Build result:

* Command: `python3 -B build_all.py statecomb`
* Output: `dist/StateComb.ZDL`
* `.audio`: 640 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* Applied object relocations: 0.
* ZDL size: 5062 bytes.

Hardware/operator result:

* With `Arm=1` and `Mix` turned up, slight comb filtering is audible.
* The comb filtering is audible whether the pedal reports the effect as active
  or bypassed.

Interpretation:

This confirms the proven `ctx[2] + 0x18` words can hold real DSP sample
history across audio callbacks, not just integer counters or magic stamps. The
audible result is small because the ring is only 16 mono samples, but it is the
first direct hardware proof that custom ZDLs can use this host block as
per-instance audio history.

The bypass observation is also important: `StateComb` intentionally does not
honor `params[0]`/OnOff, so it continues contributing audio while the pedal UI
shows bypass. Do not use diagnostic-probe bypass behavior as evidence of stock
effect bypass semantics. Production ports must explicitly respect the OnOff
state or otherwise match stock bypass behavior.

Current conclusion:

* `ctx[2] + 0x18` is persistent.
* Tested words through 19 are writable.
* The block appears per-instance for duplicate effect slots.
* The block can hold real audio-history floats.
* The remaining blocker for 1:1 `StereoChorus` is not whether host state works
  at all; it is finding a safe large-buffer mechanism for the two 65536-sample
  delay lines.

## 2026-05-13: Stock `ctx[3]` Large-Buffer Candidate

Re-disassembled stock delay/modulation effects into
`/tmp/zoom-large-buffer-trace` and inspected the instruction neighborhoods
around `ctx[3]`.

Command used:

```bash
python3 -B build/disassemble_zdl.py \
  stock_zdls/MS-70CDR_STCHO.ZDL \
  stock_zdls/MS-70CDR_DELAY.ZDL \
  stock_zdls/MS-70CDR_TAPEECHO.ZDL \
  stock_zdls/MS-70CDR_MODREV.ZDL \
  stock_zdls/MS-70CDR_STDELAY.ZDL \
  stock_zdls/MS-70CDR_ANLGDLY.ZDL \
  --out-dir /tmp/zoom-large-buffer-trace
```

Observed stock pattern:

* `DELAY`, `ANLGDLY`, `TAPEECHO`, and `STCHO` all load `ctx[3]` and read
  descriptor fields `[0]`, `[1]`, and `[2]`.
* The code then forms addresses from field `[0]`, compares generated pointers
  with field `[1]`, and subtracts/reloads field `[2]` when wrapping.
* This strongly suggests:
  * `ctx[3][0]` = large-buffer base pointer.
  * `ctx[3][1]` = large-buffer end pointer.
  * `ctx[3][2]` = wrap span / buffer byte length.
* `STDELAY` additionally doubleword-loads through a pointer path rooted in
  `ctx[3][0]`, consistent with stereo or paired sample history.

Important examples:

* `DELAY` stores a float through `ctx[3][0] + offset`, then later reads
  `ctx[3][1]` and `ctx[3][2]` around wrap checks.
* `TAPEECHO` stores computed sample history through the same descriptor shape.
* `STCHO` does multiple wrap-checked reads from descriptor memory while also
  maintaining small scalar state at `ctx[2] + 0x18`.

Working interpretation:

`ctx[2] + offset` is small per-instance scalar state. `ctx[3]` is now the best
candidate for the stock host-managed large delay/reverb/modulation buffer.

## 2026-05-13: Probe 8 - `DescComb`

Added `src/airwindows/desccomb/`, a staged hardware probe for the stock
`ctx[3]` descriptor candidate.

Purpose:

* Test whether custom ZDLs receive a valid `ctx[3]` descriptor.
* First read and validate the descriptor without writing descriptor memory.
* Then use descriptor base memory as a tiny comb ring if the read-only stage
  looks safe.

Behavior:

* `Arm=0`: pass-through, no `ctx[3]` dereference.
* `Arm=1`, `UseBuf=0`: read `ctx[3][0..2]`. If the descriptor looks plausible
  (`base < end`, aligned, at least 96 bytes, sane span), report that with
  stereo wobble using the already proven `ctx[2] + 0x18` counter.
* `Arm=1`, `UseBuf=1`: use descriptor base memory as a 16-sample mono comb
  ring, with ring index at descriptor word 16.

Testing guidance:

1. Flash only `DescComb.ZDL` for this test.
2. Load one instance with `Arm=0`, `UseBuf=0`; confirm pass-through.
3. Set `Arm=1`, keep `UseBuf=0`.
4. If this produces stereo wobble, `ctx[3]` read succeeded and the descriptor
   looks plausible.
5. Only if step 4 is stable, set `UseBuf=1`.
6. If `UseBuf=1` produces slight comb/filter coloration, descriptor base memory
   is writable DSP history and is our first proven large-buffer hook.
7. If step 3 crashes/freezes, `ctx[3]` itself is unsafe for custom ZDLs or needs
   setup we have not reproduced.
8. If step 3 passes through with no wobble, custom ZDLs may get a null/invalid
   descriptor unless metadata asks the host for one.

Build result:

* Command: `python3 -B build_all.py desccomb`
* Output: `dist/DescComb.ZDL`
* `.audio`: 1248 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* Applied object relocations: 0.
* ZDL size: 5666 bytes.

Hardware/operator result:

* `UseBuf=0`, `Arm=0`: no wobble.
* `UseBuf=0`, `Arm=1`: stereo wobble.
* `UseBuf=1`: might introduce slight comb filtering, but if so it is very
  hard to hear.

Interpretation:

The read-only stage is a strong positive result: custom ZDLs can dereference
`ctx[3]`, and `ctx[3][0..2]` look like a plausible stock buffer descriptor on
hardware. That moves `ctx[3]` from stock-disassembly hypothesis to live custom
ZDL evidence.

The write stage is inconclusive, not negative. The first `UseBuf=1` build used
only a 16-sample ring at the descriptor base, so the audible effect was expected
to be subtle. Rebuild `DescComb` with a larger descriptor-memory ring:

* Use descriptor word 0 as the ring index.
* Start sample history at descriptor word 32.
* Use a 2048-sample ring when the descriptor reports enough space.
* Fall back to 512 samples, then 128 samples for smaller descriptors.
* Increase delayed contribution so successful descriptor writes are easier to
  hear.

Build result for larger-ring version:

* Command: `python3 -B build_all.py desccomb`
* Output: `dist/DescComb.ZDL`
* `.audio`: 1760 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* Applied object relocations: 0.
* ZDL size: 6178 bytes.

Testing guidance for larger-ring version:

1. Retest `Arm=1`, `UseBuf=0` first. It should still wobble.
2. Then set `UseBuf=1`.
3. If descriptor memory is writable audio history, the effect should now be
   much easier to hear than the 16-sample version.
4. If it still barely changes sound, the descriptor may be readable but either
   not writable for custom ZDLs, not mapped to an audible delay-sized region, or
   being reset/owned by host code in a way the tiny probe does not control.

Hardware/operator result:

* Larger-ring `DescComb` with `UseBuf=1` sounds like a delay effect.

Interpretation:

This is the first hardware confirmation of the large-buffer mechanism. Custom
ZDLs receive a usable `ctx[3]` descriptor, and descriptor base memory can be
used as writable audio history. The current model is:

* `ctx[2] + offset`: small per-instance scalar/history state.
* `ctx[3][0]`: large-buffer base pointer.
* `ctx[3][1]`: large-buffer end pointer.
* `ctx[3][2]`: wrap span / byte length.

This likely matches the stock delay/modulation buffer path observed in
`DELAY`, `ANLGDLY`, `TAPEECHO`, `STCHO`, and `STDELAY`.

Remaining questions before a real Airwindows `StereoChorus` port:

1. How large is the default `ctx[3]` allocation for custom ZDLs?
2. Is `ctx[3]` per instance like the tested `ctx[2] + 0x18` state?
3. Can ZDL metadata, `gid`, stock template choice, or header payloads request a
   larger descriptor allocation?
4. Does the descriptor memory survive bypass/preset changes the same way stock
   delay/modulation memory does?
5. Can we safely split the descriptor buffer into stereo lanes for algorithms
   that need independent L/R delay histories?

## 2026-05-13: Probe 9 - `DescSize`

Added `src/airwindows/descsize/`, fixed-threshold descriptor size probes.

Purpose:

* Measure whether the default custom `ctx[3]` descriptor allocation is large
  enough for `StereoChorus`.
* Avoid a size-selection knob by building fixed-threshold variants.
* Keep hardware interaction to a single `Arm` switch per test.

Why these thresholds:

Airwindows `StereoChorus` needs two `int[65536]` delay lines. On the C674x
target, `int` is 32-bit, so the delay lines alone need:

`2 * 65536 * 4 = 524288 bytes`.

Variants:

| ZDL | Threshold |
|---|---:|
| `Dsz512K.ZDL` | 524288 bytes |
| `Dsz256K.ZDL` | 262144 bytes |
| `Dsz128K.ZDL` | 131072 bytes |
| `Dsz064K.ZDL` | 65536 bytes |
| `Dsz004K.ZDL` | 4096 bytes |

Behavior:

* `Arm=0`: pass-through, no `ctx[3]` dereference.
* `Arm=1`: read `ctx[3][0..2]`, validate descriptor shape, and wobble only if
  `ctx[3][1] - ctx[3][0]` is at least the variant threshold.
* No descriptor-buffer writes.

Testing guidance:

Flash/test one threshold at a time if the pedal dislikes multiple diagnostic
ZDLs installed together. Start with `Dsz512K.ZDL`:

1. Load `Dsz512K.ZDL`.
2. `Arm=0`: should pass through.
3. `Arm=1`: if it wobbles, the default descriptor allocation is at least
   512 KiB, enough for the raw `StereoChorus` L/R delay arrays.
4. If `Dsz512K` does not wobble, test `Dsz256K`, then `Dsz128K`, then
   `Dsz064K`, then `Dsz004K`.
5. The highest wobbling threshold is the first coarse lower bound for the
   default descriptor allocation.

Build result:

* Command: `python3 -B build_all.py descsize`
* Outputs:
  * `dist/Dsz512K.ZDL`: 4898 bytes.
  * `dist/Dsz256K.ZDL`: 4898 bytes.
  * `dist/Dsz128K.ZDL`: 4898 bytes.
  * `dist/Dsz064K.ZDL`: 4898 bytes.
  * `dist/Dsz004K.ZDL`: 4842 bytes.
* Each output:
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Hardware/operator result:

* All `DescSize` threshold ZDLs flashed and loaded cleanly.
* None of the thresholds from 512 KiB down to 4 KiB wobbled when armed.

Interpretation:

The default descriptor allocation for this custom ZDL is below 4096 bytes, at
least as measured by `ctx[3][1] - ctx[3][0]`. This is consistent with
larger-ring `DescComb` sounding like a delay only because it could fall back to
a much smaller ring. It also means the default custom descriptor allocation is
not enough for Airwindows `StereoChorus`.

Follow-up build:

Added smaller thresholds around the range `DescComb` actually used:

| ZDL | Threshold |
|---|---:|
| `Dsz003K.ZDL` | 3072 bytes |
| `Dsz002K.ZDL` | 2048 bytes |
| `Dsz001K.ZDL` | 1024 bytes |
| `Dsz0640.ZDL` | 640 bytes |

`Dsz0640` is especially important because larger-ring `DescComb` needed at
least `(32 + 128) * 4 = 640` bytes for its smallest fallback ring.

Build result for smaller thresholds:

* Command: `python3 -B build_all.py descsize`
* New outputs:
  * `dist/Dsz003K.ZDL`: 4842 bytes.
  * `dist/Dsz002K.ZDL`: 4850 bytes.
  * `dist/Dsz001K.ZDL`: 4850 bytes.
  * `dist/Dsz0640.ZDL`: 4866 bytes.
* Each new output:
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Testing guidance:

Test downward from `Dsz003K` to `Dsz0640`. If none of these wobble, the size
probe's descriptor-length measurement disagrees with `DescComb`'s write result,
and the next step should probe `ctx[3][2]`/span separately from `end - base`.

Correction / hardware-operator result:

The previous "no wobble" report was a monitoring mistake: the clean signal was
being monitored on the mixer. Retest shows all `DescSize` probes wobble,
including `Dsz512K`.

Corrected interpretation:

The default custom `ctx[3]` descriptor allocation is at least 524288 bytes as
measured by `ctx[3][1] - ctx[3][0]`. That is enough for the raw memory required
by Airwindows `StereoChorus`'s two `int[65536]` delay arrays:

`2 * 65536 * 4 = 524288 bytes`.

This removes the biggest memory-size blocker for an exact `StereoChorus` port.
The remaining ABI checks are instance isolation, reset/bypass behavior, and
safe stereo lane partitioning.

## 2026-05-13: Probe 10 - `DescIso`

Added `src/airwindows/desciso/`, a duplicate-instance isolation probe for
descriptor base memory.

Purpose:

* Test whether the large `ctx[3]` descriptor buffer is per effect instance.
* Use one installed ZDL duplicated in two FX slots, avoiding the earlier
  two-ZDL loader conflict pattern.

Behavior:

* `Arm=0`: pass-through, no `ctx[3]` dereference.
* `Arm=1`: validate `ctx[3]`, then write a role-specific magic stamp into
  descriptor base memory.
* `Role=0`: writes `0x13579BDF`.
* `Role=1`: writes `0x2468ACE0`.
* If a running instance sees a nonzero stamp from the opposite role, it reports
  that as stereo wobble.

Testing guidance:

1. Flash `DescIso.ZDL`.
2. Load one instance, set `Arm=1`, `Role=0`. It should settle to pass-through.
3. Load two `DescIso` instances in one patch.
4. Set slot 1 to `Arm=1`, `Role=0`.
5. Set slot 2 to `Arm=1`, `Role=1`.
6. Continuous wobble means both instances share the same descriptor buffer.
   Centered/pass-through means the descriptor buffer is likely per instance.

Build result:

* Command: `python3 -B build_all.py desciso`
* Output: `dist/DescIso.ZDL`
* `.audio`: 576 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* Applied object relocations: 0.
* ZDL size: 4982 bytes.

Hardware/operator result:

* Two `DescIso` instances loaded on different FX slots pass audio straight
  through when both are armed.
* This stayed true with different `Role` settings and with matching `Role`
  settings.

Interpretation:

This is the expected result for isolated per-instance descriptor memory. If two
instances shared the same `ctx[3]` base memory, opposite roles should repeatedly
see each other's magic stamp and produce stereo wobble. Working conclusion:
each FX slot gets its own large descriptor buffer.

Follow-up size question:

`Dsz512K` proves the descriptor is at least 512 KiB, but that is still only a
lower bound. Added higher thresholds to bracket the real allocation size:

| ZDL | Threshold |
|---|---:|
| `Dsz4096.ZDL` | 4194304 bytes |
| `Dsz2048.ZDL` | 2097152 bytes |
| `Dsz1024.ZDL` | 1048576 bytes |
| `Dsz0768.ZDL` | 786432 bytes |
| `Dsz640K.ZDL` | 655360 bytes |
| `Dsz576K.ZDL` | 589824 bytes |

Build result for higher thresholds:

* Command: `python3 -B build_all.py descsize`
* New outputs:
  * `dist/Dsz4096.ZDL`: 4898 bytes.
  * `dist/Dsz2048.ZDL`: 4906 bytes.
  * `dist/Dsz1024.ZDL`: 4906 bytes.
  * `dist/Dsz0768.ZDL`: 4898 bytes.
  * `dist/Dsz640K.ZDL`: 4898 bytes.
  * `dist/Dsz576K.ZDL`: 4898 bytes.
* Each new output:
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Testing guidance:

Test high to low: `Dsz4096`, `Dsz2048`, `Dsz1024`, `Dsz0768`, `Dsz640K`,
`Dsz576K`. The highest threshold that wobbles is the next coarse lower bound for
the descriptor allocation. If `Dsz4096` wobbles, add an even higher ladder.

Hardware/operator result:

* `Dsz640K` still wobbles.
* `Dsz0768`, `Dsz1024`, `Dsz2048`, and `Dsz4096` do not wobble.

Interpretation:

The descriptor allocation is at least 655360 bytes and below 786432 bytes. This
is enough for `StereoChorus`'s raw 524288-byte L/R delay-line requirement plus
roughly 128 KiB of headroom at minimum. It is not a huge pool; exact ports
should treat the descriptor buffer as precious and avoid unrelated scratch
allocations there.

Follow-up fine-size build:

Added thresholds between 640 KiB and 768 KiB:

| ZDL | Threshold |
|---|---:|
| `Dsz704K.ZDL` | 720896 bytes |
| `Dsz672K.ZDL` | 688128 bytes |
| `Dsz656K.ZDL` | 671744 bytes |
| `Dsz648K.ZDL` | 663552 bytes |

Build result for fine thresholds:

* Command: `python3 -B build_all.py descsize`
* New outputs:
  * `dist/Dsz704K.ZDL`: 4898 bytes.
  * `dist/Dsz672K.ZDL`: 4898 bytes.
  * `dist/Dsz656K.ZDL`: 4906 bytes.
  * `dist/Dsz648K.ZDL`: 4898 bytes.
* Each new output:
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Testing guidance:

Test `Dsz704K`, `Dsz672K`, `Dsz656K`, and `Dsz648K`. The highest one that
wobbles gives the next lower bound for the allocation; the lowest one that does
not wobble gives the next upper bound.

Hardware/operator result:

* `Dsz672K` still wobbles.
* `Dsz704K` does not wobble.

Interpretation:

The default custom `ctx[3]` descriptor allocation is now bracketed at
`>= 688128` bytes and `< 720896` bytes. That gives `StereoChorus`'s raw
524288-byte L/R delay-line requirement at least 163840 bytes of remaining
descriptor space.

Follow-up tighter-size build:

Added thresholds between 672 KiB and 704 KiB:

| ZDL | Threshold |
|---|---:|
| `Dsz696K.ZDL` | 712704 bytes |
| `Dsz688K.ZDL` | 704512 bytes |
| `Dsz680K.ZDL` | 696320 bytes |
| `Dsz676K.ZDL` | 692224 bytes |

Build result for tighter thresholds:

* Command: `python3 -B build_all.py descsize`
* New outputs:
  * `dist/Dsz696K.ZDL`: 4906 bytes.
  * `dist/Dsz688K.ZDL`: 4906 bytes.
  * `dist/Dsz680K.ZDL`: 4906 bytes.
  * `dist/Dsz676K.ZDL`: 4898 bytes.
* Each new output:
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Testing guidance:

Test high to low: `Dsz696K`, `Dsz688K`, `Dsz680K`, then `Dsz676K`. The
highest wobbling threshold is the next lower bound; the lowest silent threshold
is the next upper bound. Note the naming trap: `Dsz0640` means 640 bytes, while
the `DszNNNK` files mean KiB-scale thresholds.

Hardware/operator result:

* `Dsz688K` still wobbles.
* `Dsz696K` does not wobble.

Interpretation:

The default custom `ctx[3]` descriptor allocation is now bracketed at
`>= 704512` bytes and `< 712704` bytes. That leaves at least 180224 bytes above
`StereoChorus`'s raw 524288-byte L/R delay-line requirement.

Follow-up near-final size build:

Added thresholds inside the 688-696 KiB window:

| ZDL | Threshold |
|---|---:|
| `Dsz694K.ZDL` | 710656 bytes |
| `Dsz692K.ZDL` | 708608 bytes |
| `Dsz690K.ZDL` | 706560 bytes |
| `Dsz689K.ZDL` | 705536 bytes |

Build result for near-final thresholds:

* Command: `python3 -B build_all.py descsize`
* New outputs:
  * `dist/Dsz694K.ZDL`: 4906 bytes.
  * `dist/Dsz692K.ZDL`: 4906 bytes.
  * `dist/Dsz690K.ZDL`: 4906 bytes.
  * `dist/Dsz689K.ZDL`: 4906 bytes.
* Each new output:
  * `.audio`: 608 bytes.
  * `.text`: 0 bytes.
  * `.fardata`: 0 bytes.
  * Applied object relocations: 0.

Testing guidance:

Test high to low: `Dsz694K`, `Dsz692K`, `Dsz690K`, then `Dsz689K`.

Hardware/operator result:

* Reported as "works up to `Dsz689K`."
* Working interpretation: `Dsz689K` wobbles; `Dsz690K` and higher near-final
  probes do not. If that phrasing meant only `Dsz689K` was tested, the
  conservative lower bound still holds.

Interpretation:

The practical descriptor allocation result is now enough for exact
`StereoChorus` work. With `Dsz689K` wobbling, `ctx[3]` provides at least
705536 bytes. That leaves at least 181248 bytes above `StereoChorus`'s raw
524288-byte two-delay-line requirement. If `Dsz690K` was confirmed silent, the
descriptor allocation is bracketed very tightly at `>= 705536` and `< 706560`
bytes.

Decision:

Stop spending hardware time on exact byte-size probing unless a future port
needs the last kilobyte. The next useful step is to use `ctx[3]` as a bounded
per-instance arena for the first real `StereoChorus` exact-port attempt, while
continuing to keep scalar state in the small proven `ctx[2] + 0x18` area or in
the front of the descriptor arena with explicit layout.

## 2026-05-13: First `ctx[3]`-Backed `StereoChorus` Port Attempt

Replaced the old 56-sample float-ring `StChorus` experiment with a first
Airwindows-source-kernel attempt using the proven `ctx[3]` descriptor arena.

Source anchor:

* Local reference:
  `airwindows-ref/plugins/LinuxVST/src/StereoChorus/StereoChorusProc.cpp`
* Constructor/state reference:
  `airwindows-ref/plugins/LinuxVST/src/StereoChorus/StereoChorus.cpp` and
  `airwindows-ref/plugins/LinuxVST/src/StereoChorus/StereoChorus.h`

Implemented in `src/airwindows/stereochorus/stereochorus.c`:

* `ctx[3]` descriptor validation before touching large state.
* A state header at descriptor base.
* Two source-sized `int[65536]` delay arrays after the header.
* Lazy descriptor-arena clearing in 512-sample chunks, passing audio through
  until initialization completes.
* Source Speed and Depth control laws:
  `speed = pow(0.32 + (A / 6), 10)` and `depth = (B / 60) / speed`.
* Source `sweepL`, `sweepR`, `gcount`, air-compensation, integer delay write,
  three-point interpolation, and interpolation correction flow.

Known substitutions / still not release-proven:

* Source `double` math is implemented as float32 arithmetic on the C674x path.
* `sin()` is an inline approximation to avoid pulling in unproven runtime math.
* The source floating-point dither tail is not yet reproduced.
* Startup differs slightly because the Zoom descriptor arena is cleared lazily
  instead of in a desktop constructor.

Build result:

* Command: `python3 -B build_all.py stereochorus`
* Output: `dist/StChorus.ZDL`
* ZDL size: 6954 bytes.
* `.audio`: 2528 bytes.
* `.text`: 0 bytes.
* `.fardata`: 0 bytes.
* External symbols: `__c6xabi_divf` only; linker injects `divf_rts.bin`.
* Applied object relocations: 3.

Next hardware check:

1. Flash `dist/StChorus.ZDL`.
2. Load it alone in one FX slot.
3. Expect initial pass-through for a short moment while the descriptor arena is
   cleared.
4. Confirm load, bypass, Speed/Depth edits, and preset switching do not crash.
5. Then judge whether the chorus motion now resembles Airwindows
   `StereoChorus`.

Hardware/operator result:

* The ZDL loaded, but unbypassing the effect froze/crashed the pedal.
* The output became a high-pitched sine/square-like tone.

Interpretation:

The crash is gated by `params[0]`, so it happens only when the audio path starts
touching the new state code. The first suspect is not the Airwindows math yet:
all successful `ctx[3]` probes were built as `gid=2` / `Fx_FLT_*`, while this
first `StChorus` attempt was the first custom `gid=6` / `Fx_MOD_*` effect to
dereference and write `ctx[3]`. It may not receive the same descriptor contract
even though stock modulation effects do.

Follow-up safety build:

Moved `StChorus` temporarily onto the proven FLT host path:

* Manifest `gid`: `6` / MOD -> `2` / FLT.
* Audio symbol: `Fx_MOD_StChorus` -> `Fx_FLT_StChorus`.
* SONAME: `ZDL_MOD_StChorus.out` -> `ZDL_FLT_StChorus.out`.
* Added the same base/end/span plausibility checks used by `DescSize` before
  trusting the descriptor layout.

Build result:

* Command: `python3 -B build_all.py stereochorus`
* Output: `dist/StChorus.ZDL`
* ZDL size: 7018 bytes.
* `.audio`: 2592 bytes.
* `.fardata`: 0 bytes.
* External symbols: `__c6xabi_divf` only.

Next hardware check:

Retest this FLT-path `StChorus.ZDL`. If it no longer crashes on unbypass, the
next problem is learning how to request or safely access the stock MOD
descriptor contract. If it still crashes, the culprit is probably descriptor
base writes or the chorus state layout itself, not the category.

Hardware/operator result:

* The FLT-path `StChorus.ZDL` also freezes/crashes on unbypass.
* The output again becomes a high-pitched sine/square-like tone.

Interpretation:

The host category is not the primary cause. Since the crash still happens when
unbypass enables the DSP path, the next suspected boundary is inside the
descriptor-state sequence itself: descriptor read, descriptor-base header write,
delay-line clear, or full chorus processing.

Follow-up staged build:

Added a temporary `Stage` control before `Speed` and `Depth`, defaulting to
safe pass-through. This makes unbypass safe unless the operator deliberately
turns the stage up.

| Stage | Behavior |
|---:|---|
| 0 | Pass-through; do not dereference `ctx[3]` |
| 1 | Read and validate `ctx[3]` descriptor only |
| 2 | Write/reset the small state header at descriptor base |
| 3 | Clear one 512-sample chunk from each delay line, then return |
| 4 | Continue lazy clearing until initialized, then return |
| 5 | Run the current chorus core |

The third knob now uses a synthesized LineSel-cloned edit handler; the old AIR
knob3 blob is not included in this build.

Build result:

* Command: `python3 -B build_all.py stereochorus`
* Output: `dist/StChorus.ZDL`
* ZDL size: 8066 bytes.
* `.audio`: 3040 bytes.
* `.fardata`: 0 bytes.
* External symbols: `__c6xabi_divf` only.
* Symbols verified: `Fx_FLT_StChorus`, `Fx_FLT_StChorus_Stage_edit`,
  `Fx_FLT_StChorus_Speed_edit`, `Fx_FLT_StChorus_Depth_edit`,
  `ZDL_FLT_StChorus.out`.

Next hardware check:

1. Flash the new staged `dist/StChorus.ZDL`.
2. Unbypass with `Stage=0`. This should not crash; it should pass through.
3. If stage 0 is stable, test `Stage=1`, then `2`, `3`, `4`, and `5`.
4. Report the first stage that crashes or produces the high-pitched lockup.

Hardware/operator result:

* Initial unbypass without touching parameters had crashed earlier.
* After reboot, interacting with the parameters before unbypass avoided the
  crash.
* Every visible Stage position passed audio through cleanly.
* No audible change occurred with Speed and Depth at middle values.

Interpretation:

This staged result is inconclusive for the descriptor ladder. The `Stage`
descriptor used `max=5`, while the current edit handlers appear to emit a raw
float scaled by the descriptor maximum. That means full-scale Stage likely
wrote only about `5 / 100` of the usual raw knob range, and
`stage_from_raw()` rounded it back to Stage 0. So the build probably remained
in safe pass-through for all visible Stage positions.

Follow-up Stage-scaling fix:

Changed `Stage` to a normal `0..100` UI knob. Test positions now map as:

| UI value | Expected stage |
|---:|---:|
| 0 | 0 |
| 20 | 1 |
| 40 | 2 |
| 60 | 3 |
| 80 | 4 |
| 100 | 5 |

Retest those exact values and report the first one that crashes or starts
changing the sound.

Hardware/operator result:

* The pedal crashed/froze after Stage reached about UI value 12 while the FX
  was engaged.

Interpretation:

This is still consistent with Stage 1 turning on too early. The previous
decoder rounded `raw * 5`, so the Stage 1 descriptor-read path began around UI
value 10 instead of the documented value 20. Treat this as likely
descriptor-read failure until retested with fixed UI bands.

Follow-up decoder fix:

Changed `stage_from_raw()` to decode by UI bands:

| UI range | Stage |
|---:|---:|
| 0-19 | 0 |
| 20-39 | 1 |
| 40-59 | 2 |
| 60-79 | 3 |
| 80-99 | 4 |
| 100 | 5 |

Retest by setting Stage directly to 0, then 20, then 40, 60, 80, and 100. Do
not sweep slowly through the low values for this pass; the goal is to confirm
whether the first real crash boundary is Stage 1.

Hardware/operator result:

* The pedal still crashed/froze after about UI Stage 13.

Interpretation:

The Stage parameter itself is now too ambiguous to keep using. Either the
handler's raw scaling still differs from our decoder assumption, or parameter
editing while engaged is interacting badly with the staged DSP. This prevents a
clean read/write/clear boundary test.

Follow-up fixed-ZDL stage build:

Removed the `Stage` parameter entirely and replaced the single staged
`StChorus.ZDL` with fixed-stage ZDL variants:

| ZDL | Fixed behavior |
|---|---|
| `StChS0.ZDL` | pass-through; do not dereference `ctx[3]` |
| `StChS1.ZDL` | volatile read/validate `ctx[3]` descriptor only |
| `StChS2.ZDL` | write/reset the small state header at descriptor base |
| `StChS3.ZDL` | clear one 512-sample chunk from each delay line |
| `StChS4.ZDL` | continue lazy clearing until initialized, then return |
| `StChS5.ZDL` | run the current chorus core |

`dist/StChorus.ZDL` is removed by the build so the stale Stage-knob artifact
cannot be flashed accidentally. `StChS1` uses a `volatile` descriptor pointer
so the compiler cannot optimize away the descriptor read.

Build result:

* Command: `python3 -B build_all.py stereochorus`
* Outputs:
  * `dist/StChS0.ZDL`: 4394 bytes.
  * `dist/StChS1.ZDL`: 4458 bytes.
  * `dist/StChS2.ZDL`: 4778 bytes.
  * `dist/StChS3.ZDL`: 4898 bytes.
  * `dist/StChS4.ZDL`: 4930 bytes.
  * `dist/StChS5.ZDL`: 6954 bytes.
* All outputs have `.fardata`: 0 bytes.
* `StChS5` is the only variant that still needs injected `__c6xabi_divf`.

Next hardware check:

Flash/test one fixed-stage ZDL at a time, starting with `StChS0`, then
`StChS1`. Stop at the first one that crashes. This finally removes Stage-knob
scaling from the experiment.

Hardware/operator result:

* `StChS0` through `StChS4` survive.
* `StChS5` is the only fixed-stage variant that crashes.

Interpretation:

The `ctx[3]` state path is now cleared for this build: descriptor read,
descriptor-base header write, one-chunk delay clear, and full lazy delay clear
all work. The crash boundary is the chorus processing core.

The previous `StChS5` was also the only stage variant that pulled in
`__c6xabi_divf`, because it used float division in the sine approximation and
in `depth = (B / 60) / speed`. That made runtime division/helper dispatch the
next most suspicious difference.

Follow-up no-division Stage 5 build:

Changed the Stage 5 chorus core to avoid runtime float division:

* `sin_approx()` now uses a multiply-only fast sine approximation.
* `depth` now uses a bounded multiply-only reciprocal approximation for crash
  isolation.
* This is not the final 1:1 math; it is a hardware safety probe to test whether
  the divide/helper path caused the crash.

Build result:

* Command: `python3 -B build_all.py stereochorus`
* `dist/StChS5.ZDL`: 6858 bytes.
* `StChS5` now has `.fardata`: 0 bytes, no external symbols, and no applied
  object relocations.

Next hardware check:

Retest only `StChS5.ZDL`. If it survives, the divide/helper path was the likely
crash source. If it still crashes, the next split is inside the chorus core:
air compensation vs. integer delay write/read vs. output assignment.

Hardware/operator result:

* `StChS5` now survives and produces a semi-working chorus.
* The audible Speed and Depth response saturated around UI value 14.

Interpretation:

The crash boundary was likely the runtime float division/helper path, not the
`ctx[3]` descriptor state itself. The Speed/Depth saturation matches the old
shared `zoom_param_norm()` assumption that knob raw values top out around
`0.14f`; this build's controls instead behave like normal 0..1 knob values
(`0.14f` at UI 14, `1.0f` at UI 100). `StereoChorus` now uses a local parameter
normalizer until the per-handler parameter convention is fully mapped.

Follow-up control-law build:

* `StereoChorus` no longer divides Speed/Depth raw values by `0.14f`.
* The Stage 5 depth law now uses a three-step multiply-only reciprocal estimate
  for `1 / speed`, replacing the very rough crash-isolation approximation.
* This keeps `__c6xabi_divf` out of the ZDL while tracking the Airwindows depth
  curve closely enough for hardware listening tests.

Next hardware check:

Retest `dist/StChS5.ZDL`. Speed and Depth should now keep changing across the
full 0..100 UI range. If that works, the remaining non-1:1 differences are the
float32 port, the sine approximation, omitted dither, and any still-unknown Zoom
buffer/parameter conventions.

Hardware/operator result:

* The control-law build sounds like Airwindows `StereoChorus`.

Cleanup:

* Promoted the working fixed-stage 5 build to the normal release artifact
  `dist/StChorus.ZDL`.
* Removed the fixed-stage `StChS0`..`StChS5` artifacts from `dist/`.
* Changed the default `python3 -B build_all.py` path to clean `dist/` and build
  only release artifacts. Diagnostic probes remain buildable by name or with
  `--all`.

Follow-up release polish:

* Added dedicated `StereoChorus` screen art instead of reusing the ToTape-style
  image.
* Placed the two visible knob overlays explicitly at the Speed and Depth wells.
* Removed the temporary `BitCrush` verification effect from source, `dist/`, and
  the default release build list.

## 2026-05-13: ToTape9 ctx[3] Full-Kernel Probe

Now that `StereoChorus` proves the large descriptor arena can host real
per-instance delay state, `ToTape9` has moved off the old stateless beta path.

Changes:

* `ToTape9` now enables the full DSP path and uses a `ToTape9State` struct
  stored in `ctx[3]`.
* The old large `.fardata` state remains gone; all persistent tape/flutter/head
  bump/clip state is host-descriptor-backed.
* Parameter normalization now follows the 0..1 raw convention confirmed while
  fixing `StereoChorus`.
* The release image now uses the same Airwindows visual grammar as
  `StereoChorus`: title top-left, `AIRWINDOWS` top-right, effect graphic in the
  middle, knob wells along the bottom.

Build result:

* Command: `python3 -B build_all.py totape9`
* Output: `dist/ToTape9.ZDL`
* ZDL size: 17,258 bytes.
* `.fardata`: 0 bytes.
* Pre-test hardware-risk boundary: this first full-kernel probe still links
  `__c6xabi_divf`, so a freeze like early `StereoChorus` would point at the
  math-helper path before implicating state allocation.

Hardware result:

* The current `dist/ToTape9.ZDL` crashes on load on the test MS-70CDR.
* A rebuild still links mechanically, but the load shape is much larger than
  the known-good `StereoChorus` release:
  * `.audio`: 7,328 bytes.
  * 9 user parameters.
  * 7 synthesized LineSel-cloned edit handlers for knobs 3..9.
  * external symbols: `__c6xabi_divf` and `__c6xabi_call_stub`.
  * `.fardata`: 0 bytes.

Current inference:

The crash happens before we can judge the audio kernel. Do not treat it as a
failure of `ctx[3]` persistent state by itself. The next useful ToTape9 ladder
is:

1. Same manifest/descriptor/edit-handler shape with `audio_nop: true`.
2. Same 9-parameter UI shape with tiny pass-through DSP.
3. Reduced 2- or 3-parameter ToTape9 shell to isolate page 2/3 handlers.
4. Full DSP with divide/helper use removed or gated, if the UI/load shape
   survives.

## 2026-05-14: "Open-Source Coding Platform" Boundary

Community feedback correctly challenged the phrase "open-source coding
platform" as too broad for the current state of the project. The honest claim
today is narrower:

* We have a custom `.ZDL` build/link pipeline.
* The ZDL container structure and many descriptor conventions are documented.
* We have enough of the embedded ELF/runtime ABI to run simple custom effects.
* `StereoChorus` proves `ctx[3]` can host real per-instance large state.
* We do not yet have a stable SDK-style contract for arbitrary effects.

What is still missing before the pedals can be described as an open-source
coding platform:

1. Runtime lifecycle map: load, init, bypass, preset switch, duplicate
   instances, reload, and when state is cleared.
2. Stereo declaration/routing control. Stock pedals already ship stereo
   effects, but the ZDL/ELF mechanism that marks or toggles "stereo" behavior
   for custom effects is still unknown.
3. Clean edit-handler ABI for all parameter pages. The current `ToTape9`
   failure may involve the 9-parameter synthesized-handler shape.
4. Load-time limits: safe `.audio` size, descriptor count, relocation shape,
   helper symbols, category/SONAME combinations, and page 2/3 parameter limits.
5. Known supported runtime subset: math helpers, divide, `double`, stack use,
   static storage, heap, and which `__c6xabi_*` routines are safe.
6. Developer workflow: a boring template that lets someone define a manifest,
   write DSP against documented buffers/state, build one command, and know the
   expected failure modes.
7. Hardware matrix beyond the current serious target, MS-70CDR firmware 2.10.

Concrete reverse-engineering targets:

* Build the `ToTape9` load-crash ladder: same 9-param UI with `audio_nop`,
  same UI with pass-through DSP, reduced parameter shells, then helper-free DSP
  increments.
* Compare stock mono/stereo effects for header, descriptor, image info,
  category, and any ELF symbols/relocations that might declare stereo routing.
* Compare stock 6-9 parameter effects, especially LO-FI Dly style handlers, to
  replace or validate the current synthesized page 2/3 edit handlers.
* Probe `ctx[13]` and `ctx[14]` more carefully because stock modulation effects
  use them and they may matter for stereo/modulation routing.
* Add lifecycle probes for bypass, preset switching, duplicate instances, and
  reload behavior.

Repository cleanup:

* Renamed `working_zdls/` to `stock_zdls/`. The directory is not a working
  scratch area; it is the tracked stock ZDL corpus used for comparison,
  templates, and disassembly.

## 2026-05-14: Rebuild `StereoChorus` in MOD Category

`StereoChorus` belongs in the modulation category, so the release build has
been moved back from the temporary FLT safety bucket to MOD now that the
release chorus core avoids the earlier runtime divide crash and has working
parameter scaling.

Changes:

* Manifest `gid`: `2` / FLT -> `6` / MOD.
* Audio symbol: `Fx_FLT_StChorus` -> `Fx_MOD_StChorus`.
* SONAME: `ZDL_FLT_StChorus.out` -> `ZDL_MOD_StChorus.out`.
* Output rebuilt: `dist/StChorus.ZDL`.

Build verification:

* Command: `python3 -B build_all.py stereochorus`.
* ZDL size: 6,994 bytes.
* Header category bytes: `0x3c = 6`, `0x43 = 6`.
* Strings present: `Fx_MOD_StChorus`, `Fx_MOD_StChorus_init`,
  `Fx_MOD_StChorus_onf`, `ZDL_MOD_StChorus.out`.
* Strings absent: `Fx_FLT_StChorus`, `ZDL_FLT_StChorus.out`.

Hardware note:

An early MOD-category `StChorus` build froze on unbypass, but that was before
the fixed-stage split, no-divide chorus core, and parameter-scaling fix. This
new MOD release needs a clean hardware retest: load, bypass/unbypass,
Speed/Depth edits, preset switch, and duplicate-instance behavior.
