# NAM A2 Lite feasibility prototype

Status: **host-validated kernel and compiled experimental neural ZDL; neural
hardware performance not yet tested**.
A separate stage-1 pass-through shell is now built at
`build/probes/namtest/NAMTest.ZDL` (0.01). See
[the hardware test instructions](../src/hardware_probes/namtest/README.md).
It contains no neural processing. The user confirmed audio, bypass, saved
controls and power-cycle behavior on the MS-70CDR on 2026-09-23.

Stage 2 is the separate [NAMLite neural test](../src/hardware_probes/namlite/README.md),
with native-rate processing and no sample-rate conversion. Hardware performance
validation is pending.

Measured 2026-09-23 on branch `codex/nam-a2-lite-prototype`.

This experiment tests whether the small three-channel A2 Lite network can be
expressed using the original MultiStomp's DSP toolchain. It does not establish
real-time performance on an MS-70CDR. No release-ready ZDL, runtime model loader, separate cabinet IR processor, or
sample-rate converter is included. The stage-2 experimental file is ready for
manual hardware testing.

## Results

| Measurement | Result |
| --- | --- |
| Model | First (Lite) submodel of the Pico demo's `example.nam` |
| Model rate | 48,000 Hz |
| Weights | 1,871 float32 values (7,484 bytes before compilation) |
| Architecture | 23 dilated layers, 3 channels, LeakyReLU |
| Persistent state | 112,612 bytes per mono instance (about 110 KiB) |
| TI code section | 42,400 bytes (`.text`, includes embedded weight immediates) |
| Weighted products | 1,732 per sample, including final scaling |
| TI compilation | C6000 8.5.0 LTS, C674x, C99, O2, EABI, far data |
| Named undefined helper symbols | None in the compiled object |
| Host comparison | Exact float32 agreement with official NAM Core for the four test signals |
| Host throughput | Approximately 2.31 million samples/s; **not pedal timing** |

State uses caller-owned history buffers, with no heap or writable global state.
Layer calls compile to PC-relative `CALLP` instructions. This object-level check
is not a substitute for auditing the final linked ZDL at a nonzero load address.
The code size excludes the Zoom wrapper and any future rate conversion. Persistent
state excludes stack and wrapper storage.

Validation runs 16,384 samples each of silence, impulse, seeded noise, and a
440 Hz sine through both implementations at 48 kHz, starting with zero history
and upstream prewarming disabled. All four had maximum absolute error zero in
this host build. Eight-sample and 257-sample processing chunks agree exactly;
recreating/resetting the state also reproduces the result. The sine output peak
was approximately 0.645, confirming a nonzero response. This checks weight order,
residual/head accumulation, history wraparound, and block boundaries. It does not
verify TI floating-point output or audio quality on hardware.

The generator specializes weights into C instructions and accepts only the
specific supported Lite shape. It is not a general `.nam` importer. A new capture
requires regenerating and recompiling. Model weights are not checked into this
repository.

## Reproduce

Requires Python with NumPy, a host C/C++ compiler, and the TI compiler for the
cross-compilation step. Keep generated files outside the repository.

Reference revisions used:

- [Pico NAM demo](https://github.com/oyama/pico-neural-amp-modeler-demo):
  `6859450be19577002cfd24b830accb6313aca565`.
- [Official NAM Core](https://github.com/sdatkinson/NeuralAmpModelerCore):
  `0b3d3c97b0859a3a8c92a8628c4dd89a25eb5842`.
- Eigen: `776f395d2df21d4053247894060adeb44430f3d1`.
  The pinned upstream Eigen revision could not be fetched due to GitLab server
  errors, so validation used this successfully fetched revision instead.
- Model file SHA-256:
  `0aa6d5472e1fbb6d52685bf60aaa06745b3a1f0831a8133a18d0708de9b0e2ed`.

With the reference repositories in `/tmp/ms-nam-reference` and
`/tmp/ms-nam-core`, and Eigen checked out under the latter's `Dependencies/eigen`:

```sh
python3 tools/nam_prototype/generate.py /tmp/ms-nam-reference/example.nam /tmp/ms-nam-build
python3 tools/nam_prototype/validate.py /tmp/ms-nam-build /tmp/ms-nam-core
/Applications/ti/ti-cgt-c6000_8.5.0.LTS/bin/cl6x --c99 -O2 -mv6740 --abi=eabi --mem_model:data=far --keep_asm --obj_directory=/tmp/ms-nam-build --asm_directory=/tmp/ms-nam-build /tmp/ms-nam-build/nam_kernel.c
```

The generator writes `geometry.json`, the kernel, and the extracted Lite model.
Validation builds the official reference runner and writes `validation.json`.
The runner enables the official A2 fast implementation. Both host builds disable
floating-point contraction for a consistent comparison.

The network equations and weight layout were checked against NAM Core's
`NAM/wavenet/a2_fast.cpp`; upstream projects retain their respective licenses.
The example capture is an external test input, not a newly authored capture or
part of this project's distributed effects.

## Next hardware stages

1. Create a dedicated pass-through smoke-test ZDL with its intended descriptor
   and parameter layout, following [Safe DSP Rules](SAFE-DSP-RULES.md).
2. Validate per-instance allocation and initialization on hardware, then add
   staged neural processing and measure real processing cost/headroom. The
   arithmetic count and desktop throughput cannot establish this budget.
3. Address sample rate: the pedal runs at 44.1 kHz and this capture is 48 kHz.
   Use a correctly trained 44.1 kHz model or properly filtered conversion in both
   directions. Running the 48 kHz capture directly at 44.1 kHz changes its temporal
   response and is not a faithful port.
4. Check input/output calibration, startup warmup, bypass, patch recall,
   sustained audio, and coexistence with other effects before a release.

**Conclusion:** the architecture can be compiled into a small self-contained C
kernel with verified host math. Whether it is usable in real time on the original
MultiStomp remains an open hardware question.


## 2026-09-25: TREC capture crackling report

User reports the expected capture character is largely present, with bitcrushed
noise/crackling while playing. This is not a clean-hardware pass.
Examined the actual supplied Downloads/NAMLite-amptrec.ZDL, 18,770 bytes,
SHA256 `9d445680e567673cd9bbead290e090aa49c1f258f5456ef62a27e73f76e47890`,
FXID900 (capture slot1). All1871 stored float weights exactly match the supported
Lite submodel generated from `[AMP] TREC-150BLD-DIO-RAW Agro Rhythm - SM57.nam`.
DSP instructions match the existing tested block engine after verifying and
masking only relocated constant-address operands.

The generated block kernel agrees bit-for-bit with NAM Core for silence, impulse,
noise and sine, including differing host block sizes. A220Hz level sweep from
0 to1 input amplitude produced no output limiter hits at Output25; output before
level stayed below0.37 on those steady test signals. This does not establish
input calibration, transient behavior, or real-time timing on the pedal.
Results: `build/probes/namlite/amptrec-audit/`.

Pending: user's Input setting and whether the noise persists with only this
effect in the patch, Mix100/Output10. Do not attribute it to a corrupt conversion,
normal amp distortion, output clipping, or DSP overload without further evidence.
No replacement DSP build released from these findings.


### TREC recording follow-up

User supplied `Nam test.m4a`,14.72525s stereo48kHz ALAC from16-bit audio,
with screenshot Input44/Output27/Mix100 in slot2. Reported crackling persists.
Decoded waveform peaks approximately0.615L/0.453R; no digital full-scale hits.
This excludes full-scale clipping of the delivered recording, not upstream
clipping, nonlinear aliasing, or missed DSP deadlines. Other active slots and
recording path are not yet confirmed. An O3 strict-float build produces identical
5344-byte audio instructions to the current O2 engine: no performance improvement
and no replacement released. Detailed measurements: `recording-audit.json` in
`build/probes/namlite/amptrec-audit/`. Avoid claiming this compiler change fixes it.


### Full-rate speed trial 0.15

User confirmed direct recording, NAM alone, and worse crackling when other effects
are added. DSP timing is the leading hypothesis, still not hardware-measured.
Separate test at `build/probes/namlite/amptrec-speed-0.15/NAMLite-amptrec.ZDL`,
capture slot1/FXID900. Compiler UNROLL(2) changes the hot loop from6 cycles/sample
to11 cycles/two samples in the scheduled steady state (8.3% reduction for this
loop only). Do not describe this as8% total measured CPU headroom. Other compiler
experiments gave no clear improvement; O3 was identical and sample-major worse.
Four host signals match NAM Core exactly; guarded-wrapper checks and all binary
constant relocations pass. Audio5504bytes, ZDL18930bytes. Converter and dist
remain on the preceding engine. Original uploaded0.14 is saved in the trial's
rollback folder. Hardware crackling comparison remains pending.


User reports0.15 gives no audible improvement: crackling/bitcrushed artifacts
remain alongside recognizable amp character. Do not promote the speed trial
to the converter. DSP overload remains a hypothesis, not a proven root cause.

## Actual ZDL execution investigation

See [NAM runtime investigation](NAM-RUNTIME-INVESTIGATION.md). The actual
uploaded ZDL matches the host wrapper within8.94e-8 in the C674x emulator.
Current callback18,612 emulated cycles;0.15 trial17,996 (3.31% total improvement).
Older clean identity and noisy history tests both cost25,156 cycles. Raw CPU
load alone is therefore not established as the explanation; hardware history
behaviour and real memory/scheduling remain open. No converter changes made.
