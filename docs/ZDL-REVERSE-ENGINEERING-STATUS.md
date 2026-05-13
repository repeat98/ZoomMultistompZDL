# ZDL and Pedal Reverse-Engineering Status

Date: 2026-05-12

This is the working map of what we know, what is only inferred, and what
still blocks true 1:1 Airwindows ports on Zoom MS-series pedals.

## Current Conclusion

`StChorus.ZDL` is not supposed to sound 1:1 with Airwindows
`StereoChorus` yet. The current build is a small-state ABI experiment. The
Airwindows source uses a fixed-point stereo delay core with:

* `int pL[65536]`
* `int pR[65536]`
* `sweepL`, `sweepR`, `gcount`
* Air compensation state for both channels
* `lastRefL[7]`, `lastRefR[7]`, `cycle`
* dither PRNG state

The two delay lines alone are 524,288 bytes on a 32-bit `int` target. The
largest writable `.fardata` observed in the stock corpus pass was 220 bytes.
Large custom writable state has already frozen real hardware. So the missing
piece is not chorus tuning; it is the pedal's safe per-effect state strategy.

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
hardware. The first descriptor-memory write test was only weakly audible, so a
larger-ring `DescComb` build is now the active probe.

Parameter table:

| Slot | Meaning |
|---:|---|
| `params[0]` | on/off as float |
| `params[4]` | normalizer, commonly `1 / max` |
| `params[5]` | user knob 1 raw value |
| `params[6]` | user knob 2 raw value |
| `params[7]..params[13]` | user knobs 3..9 |

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
