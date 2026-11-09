# Slö long-tail IR prototype — SloIR 0.01

Built locally 2026-09-25. **WITHDRAWN: user reports a pedal freeze.**

The failing 0.01 build is preserved in `build/probes/slo-ir/failed-0.01/`;
it has been removed from `dist`. Do not install previously downloaded copies.
The failure stage and cause are not yet established. The compiler rejected
pipelining of the main work loop because it contains control flow. Its 1024-step
limit is not a cycle-time guarantee; CPU overrun and the unusually large loaded
constant bank remain separate hypotheses. No replacement is cleared for testing.
The user selected preserving the tail and separating the direct sound for a
normal dry/wet Mix control. Withdrawn candidate previously at `dist/SloIR.ZDL`, with matching
Effect Manager PNG and a normal PE Custom entry (Delay, FXID908).
This is a fixed capture prototype, not yet a general browser WAV importer.

## Preparation

Source archive: `/Users/themanro/Downloads/Walrus Audio Slo.zip`.
Only entry: Walrus Slo Dreaming.wav, mono 48kHz signed24-bit,480000frames/10s.
WAV SHA256: `30c29fcf488b313507730b46556cceca731a7c0b241867677f12acf1d383a495`.

The direct-like peak is at frame4350/90.625ms. Preparation removes that leading
alignment, zeros the first10ms after the peak, and fades the next2ms in. This is
an estimated direct/wet separation; it cannot recover wet sound masked by the
original direct pulse. The final50ms is faded to avoid an abrupt noise-floor cut.
The remaining full9.909s is retained, rather than a short cabinet-IR truncation.

Welch analysis of the tail after the direct-removal window puts approximately
99.49% of measured energy below5kHz. The prototype processes wet at11025Hz,
with65-tap4.5kHz anti-alias/reconstruction filters. The dry path remains full-rate
stereo. Wet is mono. This trades high-frequency detail for processing/storage
feasibility. A static IR cannot reproduce Slö's changing modulation or sustain.

## Engine

427 partitions of256 low-rate samples,512-point FFTs,257 positive-frequency bins.
IR and input spectra use signed16-bit coefficients with independent float scale
per partition/block. Accumulation and transforms use float32. FFT/convolution work
is advanced by at most1024 scheduler steps per8-frame callback, spread over the
whole block, rather than one long processing burst.

Working state450320bytes plus alignment; coefficient bank including scales440664
bytes. Final ZDL453410bytes; audio4896bytes. These data/storage sizes are much
larger than our other custom effects. A known working arena of at least705536bytes
is recorded in build/ABI.md, but this does not prove this effect's allocation or
large-constant loading. Invalid/undersized arenas leave dry audio untouched.
Initialization clears only2048bytes per callback. Bypass resets the tail. No
unresolved TI runtime helpers, writable static DSP state or outlined DSP code.

Wet latency:512 low-rate samples plus filter delays, about47.9ms. Dry is immediate.
Mix0=all dry,100=all wet. Level50=unity wet,75=3.375x,100=8x; useful because the
captured wet tail is quiet. Tone100 leaves the prepared wet bandwidth open;
lower values add a simple low-pass. Wet output is bounded to+/-1.

## Checks

- Full computer reference convolution, impulses including history-ring wrap and
  two seconds of seeded noise followed by silence, over12.26seconds.
- Maximum error below8.2e-7 against prepared floating-point convolution;
  approximately86dB output agreement. These validate the reduced-bandwidth,
  prepared model, not an exact full-band recreation of the original pedal.
- No scheduler overruns in those tests; this is a work-count check, not TI timing.
- Guards, exact-size and four-aligned arenas, undersized fallback, independent
  instances, incremental initialization, bypass reset, level mute and dry Mix pass.
- Final constant tables and all12 audio address relocations checked, including
  targets beyond64KB; descriptor initialization and identity checks pass.
- ZDL SHA256: `6b2de3a56a8657a6e1ff04d64de74979b9a7eb041c39cf19caac2aca4baf5844`.

## Original pedal test (withdrawn — do not repeat)

Install SloIR.ZDL through Effect Manager, then close it and refresh PE. Test SloIR
alone before trying it alongside NAM or other effects. Start Mix100/Level75/
Tone100. Wait a second, play a short chord and stop: expect only a reverb tail,
then try Mix50 for immediate dry blended in. Bypass should stop the tail.
Report whether it loads and displays correctly, whether full-wet is genuinely
reverberant, and whether the tail/audio stays smooth. Unexpected unchanged dry
at Mix100 could mean the arena guard rejected the available allocation.
Do not treat passing desktop checks as proof of safe loading or real-time timing.

Local listening preview (host engine,5s guitar plus10s decay, Mix50/Level75):
`build/probes/slo-ir/slo-ir-guitar-preview.wav`. No extra normalization was applied.

## Reproduce

Use Python with NumPy/SciPy/soundfile and the installed TI C6000 toolchain:

```
python3 src/hardware_probes/slo_ir/prepare.py
python3 src/hardware_probes/slo_ir/validate.py
python3 src/hardware_probes/slo_ir/validate_wrapper.py
python3 src/hardware_probes/slo_ir/build.py
python3 src/hardware_probes/slo_ir/audit_binary.py
```

Generated coefficients, source-derived audio and reports stay in the ignored
probe folder. The dist copy is a local test build, not a published release;
capture rights remain with its provider. NAMLite was not changed.


## Load-only diagnostic 0.02

User confirmed the freeze occurs when selecting the effect. That can execute
loading and initial audio callbacks; it does not by itself isolate the loader.
`build/probes/slo-ir/load-only-0.02/SloIR.ZDL` retains all five coefficient tables
(442972bytes) byte-for-byte and the same444016-byte constant section. Audio entry
is replaced by a32-byte ABI shuttle with no buffer writes, arena initialization,
coefficient reads or DSP processing. Same FXID908 and cover, version0.02;
controls intentionally do nothing. Expected dry-through. Local table/init audits
and10000 guarded host callbacks pass. Hardware result pending. A pass does not
prove CPU overload: state initialization and coefficient access are also disabled.
Build with `python3 src/hardware_probes/slo_ir/build_load_only.py`.


## Hardware result: load-only0.02 also freezes

User reports selection still freezes with convolution and state initialization
disabled. Both Slö builds are withdrawn; artifacts retained under failed-0.01
and failed-0.02. This narrows investigation toward loading/init, without proving
a specific bank-size limit. Short cabinet test CabIR0.03 reuses FXID908.
