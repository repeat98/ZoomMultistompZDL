# Airwindows 1:1 Port Roadmap

Date: 2026-05-12

This is the practical plan for getting from safe ABI probes to real 1:1
Airwindows ports.

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

That is the strongest current lead. `ctx[2]`, `ctx[3]`, `ctx[13]`, and
`ctx[14]` are likely host-provided state, delay-buffer descriptors, or
effect-private runtime structures. We need to map them before attempting large
Airwindows state.

## Required Milestones

### 1. Map the full audio `ctx`

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

### 3. Reproduce a small stock-style state allocation

Before Airwindows:

1. Implement a tiny delay using the discovered host state pointer.
2. Keep the delay under stock-like sizes first.
3. Prove it persists across audio blocks.
4. Prove two instances do not share state.
5. Prove bypass and preset switching reset or preserve state in the same way
   stock effects do.

Only after that should we scale toward `StereoChorus`-sized buffers.

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

1. Use `build/disassemble_zdl.py` to extract ELF from stock ZDLs, run `dis6x`,
   and summarize likely `ctx[...]` root accesses.
2. Extend `build/ABI.md` with provisional fields for `ctx[2]`, `ctx[3]`,
   `ctx[13]`, and `ctx[14]`, clearly marked as unresolved.
3. Build a state mapper plugin with one knob selecting which `ctx` slot to
   inspect and another selecting the bit to sonify. First pass:
   `src/airwindows/ctxmap/`, documented in `docs/STATE-ABI-PROGRESS.md`.
4. Build a tiny host-state delay after the mapper identifies a writable
   per-instance region.
5. Only then revisit `src/airwindows/stereochorus/stereochorus.c` and replace
   the small 56-sample ring with the actual Airwindows algorithm.

## Stop Conditions

Do not call a build a 1:1 Airwindows port if:

* it uses `.fardata` for large state;
* it compresses or substitutes the source delay/reverb/filter state;
* it uses an unrelated modulation/noise/interpolation law;
* it lacks a desktop comparison harness;
* it has not been tested across load, bypass, parameter edit, preset switch,
  and duplicate-instance cases.
