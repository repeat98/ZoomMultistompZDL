# CabIR — light hybrid cabinet bank (0.20)

A cabinet IR fitted as a **32-tap FIR + 6 biquads** (`fit.py`, the HYBRID IR
approach: github.com/Leemuzhko/HYBRID-IR), plus **Reso** (±6 dB at 140 Hz) and
**Pres** (±6 dB at 2.8 kHz) biquads whose knob 50 is an exact identity.
Fitted to the whole IR, not its first 256 taps: on the Mesa 4x12 V30 SM57 IR
(17 ms) the fit is 0.51 dB RMS / 1.8 dB worst (80 Hz–8 kHz, 1/3-oct) against
1.25 dB RMS for 0.03's 256-tap truncation — and it costs 915 emulated cycles
per callback against 2,977.

How the cost came down (all bit-exact TI vs host):
- 2,977 → 1,864: 32-tap FIR, taps-outer with the 8 samples in registers.
- 1,864 → 1,324: the 8-biquad cascade in one per-sample loop never pipelined
  (register pressure 35–44 at every ii), so it ran serially; two loops of four
  with state in locals pipeline at ii=16.
- 1,324 → 915: predicate-free output loop (clip = (|v+1|−|v−1|)/2), which may
  then pipeline safely; the range check is a branch-free flag between loops.

Build: `python3 src/hardware_probes/cab_ir/build.py <ir.wav> [--taps 32] [--peaks 4]`
Validate: `python3 src/hardware_probes/cab_ir/validate.py`
Outputs in build/probes/cab-ir. Do not publish user-owned IRs or fits of them.
0.03 (256-tap truncation of the Tonehunt MESA RECTO V30 blend) is archived in
build/ir-archive/cabir-0.03/.

## 0.20: bank of 8 + the browser loader

`cab_ir.c` now holds `CAB_SLOTS` = 8 cabs; the **Cab** knob (0–100, eight equal
ranges, float32 boundaries as `build/selector_metadata.py` and
`tools/cab_loader.js` compute them) picks one, and filter state is cleared on a
change. Knobs: Cab, Mix, Level / Reso, Pres. Cost 950 cycles, any slot.

`build.py --template` compiles once and writes `tools/cab_template/`
(`CabIR.bin` with flat slots, `cab.json` with the coefficient offsets and
SHA-256, `CabIR.png`). The template is linked with unique marker values so the
offsets are found by byte search, then the markers are overwritten.

`tools/cab_loader.js` is the browser port of `fit.py` (WAV parse, 48→44.1 kHz
Kaiser-sinc resampling, 1/6-oct target, two-start Levenberg–Marquardt, float32
stability check) plus `fillBank`, which writes only coefficient bytes. Checks:
its bank writer is byte-identical to `build.py`'s `fill_bank` for the same
coefficients; `tools/tests/cab_loader.test.cjs` covers WAV formats, resampling,
a synthetic-cab fit (< 0.6 dB), knob ranges and write/reject rules. JS fit on
the Mesa V30 IRs: SM57 0.35 dB, SM58 0.55 dB (Python: 0.51 / 0.50 — different
minima; the loader keeps the better of two starts).

`validate.py` (after `build.py a.wav b.wav`): host vs float64 reference ≥ 57 dB
below signal (float32 low-frequency biquads), exact dry/mute/guards, TI build
in the emulator bit-identical to the host build.

**Level (2026-10-02):** cabs are loudness-matched -- pink spectrum, 80 Hz-6 kHz,
in = out (`loudnessDb`, default 0) -- instead of peak at -3 dB, which played
7-9 dB quiet on hardware. The resonance then peaks at +4..6 dB; a 0.34-peak
low-heavy test signal comes out at 0.54 peak, no clipping.

## 0.30 (2026-10-06): one cab per effect, 16 slots

The Cab knob and the bank are gone. Each cab is its own effect (FXID 930..945,
identity CabSl01..16), filled by the loader into one of 16 slot templates
(`tools/cab_template/slot-NN.bin`, `cab.json` format 2) -- the NAM capture
model. A patch stores the effect ID, so a cab never changes under a patch
(0.20 stored a knob position). Files `C<slot><name[:5]>.ZDL` (<= 8 chars),
pedal name `CAB-<name>`, PE name `CabIR-<name>`. 15,450 B per file (0.20:
18,174). Cost 818 / 784 (Reso+Pres flat) cycles.

Gotcha found on the way: with ONE cab the coefficients are fixed compile-time
data, and the compiler hoisted all 40 biquad coefficients into registers --
the 8-biquad loop then failed to schedule (register pressure 34-44 at every
ii) and the callback went to 1,324. Indexing the arrays with a run-time zero
the compiler cannot see through (`s->magic - MAGIC`) keeps the loads in the
loop: 818. The bank version escaped this by accident (Cab knob index).
JS fillCab is byte-identical to build.py fill_cab; 6 cab tests.
