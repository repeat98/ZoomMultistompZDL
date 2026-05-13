# ZDL and Pedal Reverse-Engineering Status

Date: 2026-05-12

This is the working map of what we know, what is only inferred, and what
still blocks true 1:1 Airwindows ports on Zoom MS-series pedals.

## Current Conclusion

`StChorus.ZDL` has moved from the old small-state ABI experiment to the first
`ctx[3]`-backed Airwindows `StereoChorus` exact-kernel attempt. The Airwindows
source uses a fixed-point stereo delay core with:

* `int pL[65536]`
* `int pR[65536]`
* `sweepL`, `sweepR`, `gcount`
* Air compensation state for both channels
* `lastRefL[7]`, `lastRefR[7]`, `cycle`
* dither PRNG state

The two delay lines alone are 524,288 bytes on a 32-bit `int` target. That
state now lives in the proven per-instance `ctx[3]` descriptor arena, not in
`.fardata`. The current build preserves the source delay topology and control
laws, but still needs hardware validation and numerical comparison because the
Zoom C path uses float32 math, an inline sine approximation, and currently
omits the source dither tail.

Hardware note: the first MOD-category `Fx_MOD_StChorus` build loaded but froze
the pedal on unbypass with a high-pitched tone. The FLT-category follow-up also
froze on unbypass, so the current build is staged with a temporary `Stage`
control. `Stage=0` is safe pass-through; stages 1..5 progressively enable
descriptor read, header write, one clear chunk, full lazy clear, and chorus
processing.

## Source Anchors

Airwindows upstream source:

* Repository: https://github.com/airwindows/airwindows
* Source file:
  `plugins/LinuxVST/src/StereoChorus/StereoChorusProc.cpp`
* State declaration:
  `plugins/LinuxVST/src/StereoChorus/StereoChorus.h`
* Release page: https://www.airwindows.com/stereochorus/

Local reverse-engineering sources:

* `build/ABI.md`
* `docs/TI-PDF-NOTES.md`
* `docs/SAFE-DSP-RULES.md`
* `docs/AIRWINDOWS-EXACT-PORTS.md`
* `docs/STATE-ABI-PROGRESS.md`
* `/Users/jannikassfalg/coding/airwindowsZoom/ZDL_Findings.md`
* `/Users/jannikassfalg/coding/airwindowsZoom/CONTEXT.md`
* `/Users/jannikassfalg/coding/airwindowsZoom/zoom-fx-modding-ref/library/CH_2.md`

## Stock ZDL Corpus Pass

Corpus: 830 files in `working_zdls/`.

Header payload sizes:

| Header payload bytes | Count | Meaning |
|---:|---:|---|
| 56 | 754 | Standard `SIZE` + `INFO` header, ELF starts at `0x4c` |
| 232 | 24 | Extended header with `BCAB` payload before ELF |
| 312 | 52 | Extended header with `CABI` payload before ELF |

ELF/program observations:

| Observation | Result |
|---|---:|
| Files that eventually contain ELF | 830 / 830 |
| PT_LOAD segments with `memsz > filesz` | 0 |
| ZDLs with extra executable segment(s), usually at `0x7800` | 411 segment instances |
| Most common `.fardata` size | 24 bytes |
| `.fardata` > 24 bytes | 80 files |
| Largest observed `.fardata` | 220 bytes (`B1Xon_M_FILTER.ZDL`) |

Parser note: `build/zdl.py` now preserves the optional `BCAB`/`CABI` payloads
and round-trips the full 830-file corpus, except that five stock files have a
stale SIZE.ELF-size field that canonicalizes to the actual embedded ELF length:
`MS-60B_GATE_REV.ZDL`, `MS-60B_HD_REV.ZDL`, `MS-70CDR_CHURCH.ZDL`,
`MS-70CDR_DUAL_REV.ZDL`, and `MS-70CDR_TREMDLY.ZDL`.

Descriptor/image observations:

| Observation | Result |
|---|---|
| Descriptor stride | 48 bytes |
| Descriptor terminator | final entry has `pedal_flags & 0x04` |
| Most common imageInfo knob count | 3 visible knob slots |
| imageInfo knob count > 3 exists | yes, but the firmware still renders in pages |

This strongly supports the current loader rule: generated ZDLs should keep
`memsz == filesz` and should not assume a BSS-style zero-fill region.

## ZDL File Layers

1. Zoom wrapper starts with four zero bytes, `SIZE`, then `INFO`.
2. For standard files, ELF begins at offset `0x4c`.
3. For extended files, the `SIZE` block's header-size field must be honored;
   the payload between `INFO` and ELF can start with `BCAB` or `CABI`.
4. The embedded payload is TI C6000 ELF32, little-endian, `ET_DYN`.
5. The loader resolves `.rela.dyn` relocations for descriptor pointers,
   image pointers, and code address materialization.
6. The firmware finds exported symbols by name: `Dll_<Name>`,
   `Fx_<GID>_<Name>`, init/onf/edit handlers, `SonicStomp`,
   `effectTypeImageInfo`, picture, and knob info.

## Runtime Model

The audio function receives `ctx`:

| Field | Meaning |
|---:|---|
| `ctx[1]` | parameter float table |
| `ctx[4]` | dry/guitar input buffer |
| `ctx[5]` | effect/wet buffer, 8 L samples then 8 R samples |
| `ctx[6]` | output accumulator |
| `ctx[11]` | magic destination indirection |
| `ctx[12]` | magic source |

Current custom effects mostly process `ctx[5]` in place and preserve the
`ctx[11]`/`ctx[12]` shuttle. Stock LineSel shows that the output buffer is
additive, not a simple replacement sink.

Stock stateful effects use more fields than this minimal custom map. A quick
disassembly pass over stock `STCHO`, `CHORUS`, `DELAY`, `HALL`, and
`TAPEECHO` shows early reads from `ctx[2]`, `ctx[3]`, `ctx[13]`, and
`ctx[14]` in addition to the fields above. These are now the primary suspects
for host-provided effect state, delay-buffer descriptors, or related runtime
structures. Use `build/disassemble_zdl.py` for repeatable stock-effect
summaries, and see `docs/AIRWINDOWS-1TO1-PORT-ROADMAP.md`.

Hardware probes now show that custom ZDLs can write persistent words through
stock-style derived state blocks at `ctx[2] + 0x10` and `ctx[2] + 0x18`.
Words 0, 12, 18, and 19 wobble successfully at both bases. A duplicate-instance
probe did not show cross-instance stamp leakage, so `ctx[2] + 0x18` is currently
treated as likely per-instance for the tested words. `StateComb` then used
words 0..15 plus word 18 at `ctx[2] + 0x18` as a tiny 16-sample comb history,
and hardware produced audible comb filtering. This is enough for small scalar
or very small audio-history DSP state, but not enough for large Airwindows
delay/reverb history.

Diagnostic probes that ignore `params[0]` can still contribute audio while the
pedal UI reports bypass. Production ports must explicitly honor OnOff/bypass
state or reproduce stock bypass behavior.

The strongest current large-buffer candidate is `ctx[3]`. Stock `DELAY`,
`ANLGDLY`, `TAPEECHO`, and `STCHO` read fields 0, 1, and 2 from `ctx[3]`, then
use the values as a base pointer, end pointer, and wrap/span while reading or
writing sample history. `DescComb.ZDL` confirms custom ZDLs can read `ctx[3]`
and see a plausible descriptor: `Arm=1`, `UseBuf=0` produced stereo wobble on
hardware. The larger-ring `UseBuf=1` build then sounded like a delay effect,
confirming descriptor base memory is writable audio history for custom ZDLs.

Current large-buffer model:

| Field | Working meaning |
|---:|---|
| `ctx[3][0]` | large-buffer base pointer |
| `ctx[3][1]` | large-buffer end pointer |
| `ctx[3][2]` | wrap span / byte length |

The remaining Airwindows blocker has narrowed: we no longer need to find
whether a large-buffer hook exists; we need to measure/default-size it, prove it
is per instance, and learn whether metadata can request enough memory for
`StereoChorus`-class delay lines.

`DescSize` confirms the default custom descriptor allocation is at least 512
KiB as measured by `ctx[3][1] - ctx[3][0]`: `Dsz512K` wobbles on hardware. That
clears the raw memory requirement for `StereoChorus`'s two `int[65536]` delay
arrays. `DescIso` then showed two armed instances in different FX slots pass
through with opposite roles, so the large descriptor buffer is currently treated
as per instance. `Dsz689K` wobbles; if the "works up to 689K" report means
`Dsz690K` and higher were silent, the allocation is bracketed at at least
705,536 bytes and below 706,560 bytes. Even under the more conservative reading
of only `Dsz696K` being silent, the confirmed lower bound is now 705,536 bytes.
That is enough to stop size probing for `StereoChorus` and start the exact-port
layout work.

Parameter table:

| Slot | Meaning |
|---:|---|
| `params[0]` | on/off as float |
| `params[4]` | normalizer, commonly `1 / max` |
| `params[5]` | user knob 1 raw value |
| `params[6]` | user knob 2 raw value |
| `params[7]..params[13]` | user knobs 3..9 |

## `ctx[]` Field Status

Known enough for production experiments:

| Field | Status |
|---:|---|
| `ctx[1]` | parameter float table |
| `ctx[4]` | dry/guitar input buffer |
| `ctx[5]` | current effect/wet buffer, 8 L samples then 8 R samples |
| `ctx[6]` | output accumulator on effects that add instead of process in place |
| `ctx[11]` / `ctx[12]` | magic shuttle; preserve every audio call |
| `ctx[2] + 0x10` | small writable persistent per-instance state block, stock `DELAY` pattern |
| `ctx[2] + 0x18` | small writable persistent per-instance state block, stock `STCHO` / `TAPEECHO` pattern |
| `ctx[3][0..2]` | large per-instance descriptor: base, end, span/length |

Still unresolved:

| Field | Current evidence |
|---:|---|
| `ctx[13]` | pointer-like in stock modulation/reverb disassembly; not needed for current `StChorus` port |
| `ctx[14]` | pointer-like in stock modulation disassembly; not needed for current `StChorus` port |
| other `ctx[]` slots | either unmapped or only observed as stable/position-dependent words in early bit probes |

## Why 1:1 Airwindows Ports Need More RE

A 1:1 port needs three separate things to be true:

1. The manifest matches source parameters: names, order, defaults, labels,
   and control laws.
2. The DSP kernel is the source algorithm, with only mechanical changes for
   the C674x toolchain.
3. Persistent state survives across audio calls exactly like the source
   plugin instance state.

The first item is mostly solved. The second is tractable for stateless or
small-state plugins. The third is the hard blocker for chorus, delay, tape,
and reverb effects.

## Exact-Port Workflow

For each Airwindows plugin:

1. Pin the exact upstream source path and commit/date in the plugin docs.
2. Copy parameter names/defaults/display rules into `manifest.json`.
3. Extract a pure C kernel with an explicit state struct.
4. Build a desktop comparison harness that runs upstream Airwindows and the
   C674x-shaped kernel on identical test vectors.
5. Preserve source math unless a replacement is documented and measured.
6. Do a ZDL `audio_nop` smoke test.
7. Add the exact kernel only after state allocation is proven safe.
8. Hardware-test load, bypass, preset switching, parameter edits, and audio.

Anything that skips step 7 is an experiment, not a port.

## Open Questions

Highest priority:

* Where does stock firmware keep state for delay/reverb/modulation effects?
  The stock corpus does not show large writable ELF memory, so the likely
  answers are host-managed scratch, hidden runtime allocation, or state in
  structures reached through handler callbacks.
* What exactly are `ctx[11]` and `ctx[12]`, and is the shuttle required once
  we write more complex stateful effects?
* What are the semantics of extended `BCAB` and `CABI` header payloads?
* Can we safely reproduce stock extra executable segments at `0x7800` for
  effects that need the same shape?
* What does the stock `_init` path initialize beyond parameter writes?

Useful experiments:

* Build a probe that writes a visible/audio signature from selected `ctx`
  fields to map additional runtime pointers. First pass added as
  `src/airwindows/ctxmap/`; see `docs/STATE-ABI-PROGRESS.md`.
* Diff stock delay/mod/reverb effects with `.fardata` > 24 bytes to identify
  whether their state is real DSP history or only small UI/control state.
* Decode the preserved `BCAB`/`CABI` payload fields across all 76
  extended-header files.
* Build a tiny state-stress ladder: 24, 40, 48, 76, 128, 220, 512 bytes of
  initialized `.fardata`, one variable changed per flash.
* Create a desktop Airwindows equivalence harness before touching hardware
  for any "exact" claim.
