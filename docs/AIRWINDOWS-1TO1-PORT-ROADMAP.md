# Airwindows 1:1 Port Roadmap

Date: 2026-05-13

This is the practical plan for getting from safe ABI probes to real 1:1
Airwindows ports.

Current status update: `ctx[3]` is no longer just a lead. Hardware probes and
the working `StereoChorus` release show it is a usable per-instance descriptor
arena for large state. The next blocker is more specific: current `ToTape9`
crashes on load with the full 9-parameter, synthesized-handler,
helper-linking build shape. That must be split before we can judge the
Airwindows tape kernel itself.

## What the TI PDFs Tell Us

The PDFs in `docs/` explain the C6000 architecture and toolchain, but not
Zoom's private effect-host ABI. They do tell us what *not* to assume:

* `B14` is the data page pointer (`DP`) for the currently active object.
  If Zoom does not set it for our object, near globals/statics are unsafe.
* Near global/static data goes through DP-relative `.bss` addressing.
  Therefore custom plugin objects must reject `R_C6000_SBR_*` and
  `R_C6000_SBR_GOT_*` until we deliberately implement DSBT/GOT support.
* `--mem_model:data=far` is required for custom C so scalar globals do not
  silently become DP-relative.
* Initialized far variables go in `.fardata`; uninitialized far variables go
  in `.far`.
* Normal C startup initializes `.bss`, `.far`, `.cinit`, constructors, stack,
  and heap. A ZDL audio callback is not normal C startup. If the Zoom loader
  does not do that work, we cannot rely on it.
* Heap allocation uses `.sysmem` plus RTS support. Treat `malloc`/`calloc` as
  unavailable for plugins until proven otherwise.
* Copy tables, `.cinit`, `SHT_TI_INITINFO`, DSBT, GOT, TLS, exceptions, and C++
  constructors are all real TI mechanisms, but supporting them means writing
  loader/runtime behavior. They are not free just because the compiler can emit
  them.

So the manuals validate our conservative build rules. They do not answer where
stock Zoom effects keep large delay/reverb state.

## New Stock-Effect Clue

Disassembling stock stateful effects shows that they use more of the `ctx`
structure than our custom effects currently map.

Observed audio-entry reads:

| Stock effect | Early `ctx` fields used in audio |
|---|---|
| `MS-70CDR_STCHO.ZDL` / `CHORUS.ZDL` | `ctx[1]`, `ctx[2]`, `ctx[3]`, `ctx[5]`, `ctx[11]`, `ctx[12]`, `ctx[13]`, `ctx[14]` |
| `MS-70CDR_DELAY.ZDL` | `ctx[1]`, `ctx[2]`, `ctx[3]`, `ctx[5]`, `ctx[11]`, `ctx[12]` |
| `MS-70CDR_HALL.ZDL` | `ctx[1]`, `ctx[2]`, `ctx[3]`, `ctx[5]`, `ctx[11]`, `ctx[12]` |
| `MS-70CDR_TAPEECHO.ZDL` | same family of fields, plus dense reads/writes through a structure loaded from `ctx[1]`/`ctx[2]` |

That was the strongest lead, and the `ctx[3]` part is now confirmed enough for
custom ZDLs: `ctx[3][0..2]` describe a host-managed large buffer. `ctx[2]`
small state and `ctx[13]`/`ctx[14]` still deserve mapping, but they no longer
block every large-state Airwindows attempt.

## Required Milestones

### 1. Keep mapping the full audio `ctx`

Build tiny hardware probes that read one candidate field at a time and encode
the result audibly or visibly. Do not dereference unknown pointers first.

Probe order:

1. Log or sonify raw values of `ctx[0..15]`.
2. For pointer-looking values, test read-only dereferences of word `0`.
3. Test small writes only to fields proven writable by stock disassembly.
4. Compare values across effect load, bypass, parameter edit, preset switch,
   and two instances of the same effect.

The two-instance test matters: Airwindows plugin state must be per effect
instance, not one static global shared by every slot.

### 2. Understand stock state descriptors

Use stock `Delay`, `STCHO`, `Hall`, `ModRev`, and `TapeEcho` as the corpus.
For each:

1. Extract ELF with `build.zdl.Zdl`.
2. Disassemble `.audio` and `_init`.
3. Identify every access rooted in `ctx[2]`, `ctx[3]`, `ctx[13]`, `ctx[14]`,
   and parameter-table structures.
4. Classify each as scalar state, circular-buffer pointer, buffer length,
   wrap limit, coefficient, or host callback.
5. Diff effects to find common layouts.

Goal: a documented struct map, not just "some pointer probably works".

### 3. Keep the proven `ctx[3]` state path load-safe

`StereoChorus` proves the large-buffer route can work. For each new stateful
plugin:

1. Validate `ctx[3][0..2]` before use.
2. Keep `.fardata` at 0 or tiny.
3. Initialize large memory lazily across audio callbacks.
4. Prove two instances do not share state.
5. Prove bypass and preset switching reset or preserve state in a documented
   way.

### 4. Build a desktop Airwindows equivalence harness

For each target plugin:

1. Vendor or reference the exact upstream Airwindows source path/commit.
2. Extract the DSP into a plain C kernel with an explicit state struct.
3. Run upstream Airwindows and the C-shaped kernel on identical impulses,
   tones, silence, and randomized blocks.
4. Compare output within a defined tolerance.
5. Freeze parameter laws and defaults in `manifest.json`.

This separates "does the Airwindows port match source?" from "does the pedal
loader run it?"

### 5. Port the exact kernel onto the proven state strategy

For `StereoChorus`, the target state is:

* two `int[65536]` delay lines;
* `sweepL`, `sweepR`, `gcount`;
* air compensation histories;
* `lastRefL[7]`, `lastRefR[7]`, `cycle`;
* dither PRNG state.

At 44.1 kHz on the pedal, `cycleEnd` should be `1`, so the high-sample-rate
undersampling reference path can be mechanically retained but should stay
inactive unless the host rate is ever proven different.

## Immediate Work Items

1. Build a ToTape9 load-safety ladder:
   * same 9-parameter descriptor/edit-handler shape with `audio_nop: true`;
   * same UI shape with tiny pass-through DSP;
   * reduced 2- or 3-parameter shell to isolate page 2/3 handlers;
   * full DSP with divide/helper use removed or gated.
2. Focus the first ToTape9 split on synthesized/edit-handler behavior. The
   stock corpus contains many 9-parameter effects, and ToTape9's current
   executable load size is within stock bounds, so parameter count and raw size
   are less suspicious than handler shape or runtime helper use.
3. Add a desktop equivalence harness before calling ToTape9 1:1.
4. Continue mapping `ctx[2]`, `ctx[13]`, and `ctx[14]` from stock delay,
   modulation, and tape effects.
5. Record every hardware result in `docs/STATE-ABI-PROGRESS.md` before moving
   the claim into release docs.

## Stop Conditions

Do not call a build a 1:1 Airwindows port if:

* it uses `.fardata` for large state;
* it compresses or substitutes the source delay/reverb/filter state;
* it uses an unrelated modulation/noise/interpolation law;
* it lacks a desktop comparison harness;
* it has not been tested across load, bypass, parameter edit, preset switch,
  and duplicate-instance cases.
