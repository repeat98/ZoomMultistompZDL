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
  working_zdls/MS-70CDR_STCHO.ZDL \
  working_zdls/MS-70CDR_DELAY.ZDL \
  working_zdls/MS-70CDR_HALL.ZDL \
  working_zdls/MS-70CDR_MODREV.ZDL \
  working_zdls/MS-70CDR_TAPEECHO.ZDL \
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
