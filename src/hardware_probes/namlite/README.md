# NAMLite — experimental neural effect

Current local candidate: **0.12 Marlboro Smokey Amp**, hardware validation pending.
See the final section for the current build and test; earlier sections are an
investigation log, not installation instructions.

Original version 0.02, Delay category, GID 8 / FXID 498. Separate from
NAMTest (497), whose pass-through, bypass, saved controls and power-cycle checks
were confirmed on the user's MS-70CDR on 2026-09-23.

## Build

From repository root, with Python/NumPy and the TI C6000 compiler installed:

```sh
python3 src/hardware_probes/namlite/build.py /path/to/example.nam
python3 src/hardware_probes/namlite/validate_host.py
```

Use the reference model and revision recorded in
[the prototype notes](../../../docs/NAM-A2-LITE-PROTOTYPE.md).
Output: `build/probes/namlite/NAMLite.ZDL`. Weights are generated from the external
model and embedded in the compiled DSP, not loaded from a file on the pedal.
The generated sources and extracted model remain in the ignored probe directory.
See THIRD-PARTY-NOTICES.txt for upstream licenses.

## First pedal check

1. Install NAMLite.ZDL through Effect Manager and close Effect Manager afterward.
2. Refresh PE, select NAMLite from the normal Custom list and put it alone in a test patch.
3. Start with Input 50, Output 25, Mix 0. This should pass the dry guitar.
4. At a low listening volume, raise Mix to 25, then 100. Allow about a quarter
   second for warmup/fade. Listen for a changed amp-like tone and any crackling,
   dropouts or stalled controls. Even Mix 1 engages the full neural workload.
5. Return Mix to 0 or bypass to compare with dry. Output 0 should mute the wet
   path at Mix 100 once smoothing settles. Input controls drive into the model.

This file has not yet been verified on hardware. Please report whether the
sound changes when Mix rises and whether audio/UI remain stable. Do not infer
successful neural execution from the presence of dry audio alone: an invalid or
undersized arena deliberately leaves dry audio untouched.

## Intentional limitations

- The example model is labeled "Logic Pro Amp" in its source metadata. One fixed
  three-channel A2 Lite network; not a general NAM loader.
- Native 44.1 kHz execution of a 48 kHz capture. There is **no rate conversion**,
  so this tests feasibility rather than faithful capture reproduction.
- One mono network receives the average of L and R. Dry remains stereo; wet is
  duplicated to both outputs.
- Input and Output use linear gain: 0 = zero, 50 = unity, 100 = 2x. Default output
  is 25 (0.5x). Input and wet output are bounded to +/-1 for this first test.
- The normal descriptor cost value inherited from the linker is not a measured
  neural CPU estimate. Test alone; hardware headroom is unknown.
- Mix 0 fades to exact dry and parks processing. Re-engaging Mix resumes state;
  bypass/re-engage runs silent warmup again to flush the old history.
- Invalid network output causes reinitialization. There is no status display for
  this recovery or for insufficient memory in this test build.

## Implementation checks

The arena requirement is 112,644 bytes, aligned to eight bytes. History clearing
is bounded to 512 floats per callback. Neural warmup processes eight samples per
callback for 8,192 samples, not one long initialization loop. All model helpers
are forcibly inlined into the sole `.audio` entry to avoid outlined calls and
runtime dependencies. Build checks reject unexpected helper symbols, writable
static sections, nonempty `.text` or jump tables.

The host wrapper test checks guarded state bounds, undersized arena handling,
context shuttle, untouched output accumulator, default dry, bypass, independent
instances, warmup, finite bounded neural output, output mute, and parked processing
at Mix 0. Host tests do not establish TI execution speed or hardware stability.

## Built artifact (2026-09-23)

`NAMLite.ZDL`: 47,166 bytes. Audio section 42,208 bytes; maximum compiler-reported
stack frame 96 bytes. Final disassembly contains no audio helper calls or
computed audio branches other than returns. Descriptor/init checks and init
branch rebasing at three addresses passed. No FXID collision with the current
stock/custom/probe database or other source manifests was found.

SHA-256: `b9d7fe4e762ea00934190ddf7c3d91c24cef9942d69b91a29e8fbb826b6db159`.

Generated `host-validation.json` and `binary-validation.json` in the output
directory record local checks. Hardware test remains pending.

## Loader isolation 0.03 (working fallback)

User reports NAMLite 0.02 remains an empty block on hardware. Neural execution
is therefore unconfirmed. Compiled code was 44,384 bytes including wrappers,
versus 16,576 for the largest working pack effect (Spool); size is a hypothesis,
not a demonstrated loader limit.

`build_loader_check.py` creates version 0.03 with the same Delay identity, cover,
three parameters and initialization. It contains only a small input/output gain
and mix DSP (640 audio bytes; 5,598 byte ZDL), no arena and no neural model.
Host tests verify dry, mute, unity, half gain, bypass and context shuttle; parsed
identity/parameters match PE and the initialization byte comparison passes.
The neural 0.02 binary is preserved in `build/probes/namlite/neural-0.02/`.

Replace the installed NAMLite with 0.03, then select directly on the pedal.
At Mix 100, Output 0 should mute. If this small version also remains invisible,
focus on installation/identity rather than inference math. If it loads, isolate
code-size and audio-execution effects next. This is not a claim of a NAM fix.

## Full-size isolation 0.04 (FAILED — do not install)

User confirmed that small version 0.03 works. Version 0.04 retains the exact
47,166-byte neural 0.02 file and section layout. Only the header version and
first 32 audio bytes change. The audio entry becomes the hardware-confirmed
NAMTest context shuttle and return, making all remaining neural code unreachable
through the audio callback. No arena access or neural processing is performed.

Build with `python3 src/hardware_probes/namlite/build_fullsize_check.py`.
The builder checks the baseline hash, pass-through bytes, exact allowed byte
differences, unchanged file length, and matching parsed identity/parameters.
Disassembly confirms the entry returns after the context shuttle.

Install `dist/NAMLite.ZDL` version 0.04 and select NAMLite directly under Delay.
Expected: visible name/controls and unchanged dry sound, on or off. Knob movement
should not change sound. If it loads, full-file size alone is not the cause of
the earlier failure; investigate neural execution and state setup. If it fails,
continue investigating loader/layout limits. Hardware result is pending.

Working 0.03 remains at `build/probes/namlite/loader-check/NAMLite.ZDL`.

### Hardware result: 0.04 freezes on load

User reported a load-time pedal freeze for 0.04. The local `dist/NAMLite.ZDL`
has been restored byte-for-byte to working 0.03 (SHA-256
`27c0b444bed12372a71d9cb63717d6a92064f95a9b5027299417c21cc97d9e8a`).
Do not distribute or reinstall 0.04. No hardware writes were performed by the agent.

The failure occurs with neural instructions unreachable from the audio entry.
This rules out neural inference workload as a necessary cause of this freeze.
It does not prove a specific code-size limit: large-layout registration/init
addresses and other loader behavior still need investigation. Recovery precedes
any further hardware tests.

## Compact neural test 0.05 (hardware loads; fidelity unverified)

Built from the user-supplied CD BHS Singularity Fuzz Lite capture. The generic
loop kernel stores 1,871 float weights plus shape metadata in read-only `.const`
sections. The existing linker's const-section and absolute address relocation
support is used; no linker changes were needed.

- ZDL: 15,906 bytes (old neural file: 47,166).
- Audio: 2,944 bytes; full code including handlers: 5,120 bytes.
- Read-only constants: 8,480 bytes; no object writable static state.
- State: 112,644 bytes, with internal alignment rather than rejecting a host
  buffer aligned to only four bytes. Up to seven padding bytes may be needed.
- SHA-256: `c9f2ce1d526ce3c0981658973827b14f6acb765e0015f35ff31c5f2caa954bb3`.

Exact host agreement with official NAM Core on all four reference signals,
block partition and reset checks. Guarded wrapper tests also pass, including
a four-aligned arena. All 11 audio constant-address relocations have in-range
read-only targets and correct instruction halves; model tables match the object
exactly. Init rebasing, absence of audio helper calls and PE identity were checked.
The user subsequently confirmed loading and audio without freezing, but reported
excessive noise and a bitcrushed character. Audio fidelity, real-time timing, and
the cause of the earlier large-build freeze remain unproven.

Build: `python3 src/hardware_probes/namlite/build_compact.py /path/to/capture.nam`.
Validate the kernel with `tools/nam_prototype/validate.py` against NAM Core, and
the wrapper with `validate_host.py --build build/probes/namlite/compact`.
Output is isolated under `build/probes/namlite/compact`; copying to dist is manual.

Input 50 / Output 25 / Mix 0 starts dry. First confirm the pedal displays the
effect. Then raise Mix to 25 and 100 to engage the neural workload. Test alone.
This remains native 44.1kHz execution of a 48kHz capture, without resampling.

## Quiet-input investigation and 0.06

The Singularity Lite model has approximately 56.5 dB small-signal gain at 220 Hz.
An input sine of peak 0.0001 yields AC RMS 0.047; peak 0.001 already yields
AC RMS 0.204. Official NAM Core and the compact host kernel agree exactly across
eight levels from silence through peak 1. No output limiting occurs in this
sweep at Output 25. Silence settles to DC 0.004204, with no sustained AC noise.
This supports noise-floor amplification by the capture as a contributor, but
does not exclude a target-only arithmetic, timing, or input-level problem.

Version 0.06 changes only Input's gain law below unity: `g=(2*Input/100)^2`.
Above 50 the old linear law remains. Input 1/5/10/25/50 now corresponds to
approximately -68/-40/-28/-12/0 dB. Output and Mix, model coefficients, sample
handling, and network math are unchanged. Existing patches below Input 50 will
sound less driven; 50 remains unity. No gate or sample-rate conversion was added.

The 15,838-byte build passed reference comparisons, wrapper tests including
actual smoothed input gains, guarded buffers, and constant-table relocation
checks. Hardware testing of 0.06 is pending. Previous 0.05 is preserved under
`build/probes/namlite/compact-0.05/`; 0.03 remains in `loader-check/`.

Test alone at Mix 100 / Output 25 / Input 1, then 5 and 10. At Input 0, allow
one second for smoothing/history to settle: persistent hash would not match the
host's silent-input result. This is an isolation test, not a verified bitcrush fix.

Reproduce the level audit after `validate.py` with:
`python3 tools/nam_prototype/audit_levels.py build/probes/namlite/compact`.

## Identity diagnostic 0.07 (hardware: clean)

The user confirmed that the 0.07 clean diagnostic sounded fine on the pedal.
This result must not be treated as an outstanding test or as proof that history
handling works. The user reports 0.06 improved the sound, but it still has a consistent bitcrushed
texture, not intermittent crackling. Gain alone has not resolved the complaint.

0.07 replaces the fuzz weights with an analytically constructed unity network.
Its audio instructions, section layout, state allocation, relocation records,
parameter handling and loop counts are byte-identical to 0.06. Only the version
and coefficient table differ. The diagnostic executes all 23 layers and the
head. Opposite-sign channels cancel the LeakyReLU nonlinearity. This is a test
model, not a captured amp or a replacement fuzz effect.

Host checks: exact agreement with NAM Core on all four standard signals;
maximum identity error below 3.6e-7 on full-range random audio; exact silence;
guarded wrapper and parameter tests pass. These do not verify real-time pedal
execution. Zero older-tap weights also mean this test cannot validate nonzero
dilated history contributions or prove capture fidelity if it sounds clean.

Install 0.07 alone. Set Input 50, Output 50 and compare Mix 0 against Mix 100,
waiting a second after changes. A mono guitar should remain clean at both.
If full wet has the bitcrushed texture, investigate the target execution/input
range/timing path; if clean, next isolate nonzero history taps and nonlinear
model behavior. Do not interpret a clean result as proof of a faithful NAM port.

Build: `python3 src/hardware_probes/namlite/build_identity_check.py`.
Outputs: `build/probes/namlite/identity-check/`. Run the usual `validate.py`,
then `tools/nam_prototype/validate_identity.py` and guarded wrapper tests.
0.06 fuzz is preserved at `build/probes/namlite/compact-0.06/NAMLite.ZDL`.

## Megaphone 609 capture 0.08 (hardware: bitcrushed)

At the user's request, the next listening test uses their `Megaphone 609.nam`,
modeled by `mikefromtilt` (metadata: Pyle Megaphone, TONE3000). Its 48 kHz
SlimmableContainer includes the supported 3-channel, 1,871-weight Lite submodel.
Source SHA-256: `8564c5852973efd39230a050488bba013595695f83dc3e791574e84bb6f6fa4d`.

The 15,838-byte binary differs from 0.06 only in version and model weights;
DSP code, layout, relocation records and controls are identical. It retains
0.06's finer Input attenuation. Host output matches NAM Core exactly on silence,
impulse, noise and sine tests; block/reset invariance and guarded wrapper tests
also pass. The user reports the same bitcrushed character on hardware; switching
captures did not resolve it. Real-time timing remains unmeasured.
The original capture stays outside the repo;
generated weights and reports are under `build/probes/namlite/megaphone-0.08/`.
This is a local experimental build, not a published release or a confirmed fix
for the bitcrushed texture. The 0.07 diagnostic was confirmed clean on hardware
and remains available under `build/probes/namlite/identity-check/`.

Build with `build_compact.py /path/to/model.nam --version 0.08 --output
build/probes/namlite/megaphone-0.08`. Start alone with Input 50 / Output 25 /
Mix 100; compare Mix 0 after a second, adjusting Output for listening level.
The 48 kHz capture still runs at 44.1 kHz without resampling.

## History diagnostic 0.09 (hardware: delayed and bitcrushed)

User reports the expected delay but continued bitcrushed texture. Combined with
clean 0.07, this implicates history-dependent processing or behavior exposed by
the nontrivial weights; it does not identify the precise memory/arithmetic/timing
fault. Stop changing captures and gain to investigate this result.

This test runs the same binary instructions/layout as 0.06–0.08. Only the
coefficient table and version differ. Each layer reconstructs its longest-delayed
input through an opposite-sign LeakyReLU pair and residual subtraction. The head
sums telescope, adding back the conditioned input, then applies a 15-sample head
delay. All 23 layer history regions contribute. Total: 6,346 samples, or 143.9 ms
at the pedal's 44.1 kHz rate. It is a clean, single delay with no feedback.

The raw head emits -2 for its first 15 samples while its bias-cancelling history
fills; the unchanged 8,192-sample muted warmup hides this before wet output.
Host output matches NAM Core exactly on the four reference signals. Independent
delay tests cover impulse, random, quiet, alternating and silence over 65,536
samples with two block sizes. Maximum error against the expected delayed signal
is below 4.4e-6. Guarded wrapper, mute, bypass and parameter tests pass.

Build: `python3 src/hardware_probes/namlite/build_identity_check.py --history`.
Outputs: `build/probes/namlite/history-check/`. Run `validate.py`, then
`tools/nam_prototype/validate_history.py`, plus the guarded wrapper checks.

Test alone at Input 50 / Output 50 / Mix 50 for a dry note and one clean repeat;
Mix 100 should give only the delayed note. A bitcrushed repeat would implicate
the history-dependent path, though it would not identify the exact fault. A
clean result would narrow the problem to behavior this synthetic network does
not cover; it would not prove capture accuracy or worst-case DSP timing.


## Block execution candidate 0.10 (hardware: user reports improvement)

The clean 0.07 identity result does not exclude missed processing deadlines:
unchanged dry output can resemble correctly processed identity output. The
0.09 delay is intentional, but its bitcrushed texture is not. No confirmed
hardware root cause has been identified; host agreement alone is insufficient.

0.10 restores the same Megaphone capture used in 0.08 and rewrites neural
execution to process each eight-frame callback layer by layer. Weights are
reused across those frames; planar history and scratch channels have padding to
stagger memory-bank accesses. Ring capacities include the seven future frames
written before convolution, including a 32-frame head ring. Disjoint scratch
pointers allow the TI compiler to schedule loads/stores more freely. This is an
execution/locality improvement candidate, not a measured pedal speedup.

The builder explicitly disables floating-point reassociation. On this build,
that flag did not change the binary. Input/Output/Mix and model equations remain
unchanged. State version increments so the new layout is initialized safely.
The wrapper requires 133,360 bytes plus up to seven alignment bytes. History
clearing and neural warmup remain bounded across callbacks.

- ZDL: 18,294 bytes; audio: 5,344 bytes; no unresolved audio helpers.
- SHA-256: `75af32b74777df8d7c81b7ef75e9a150cdd7a56ba05de00ad7f3b7bf141a5fcb`.
- Exact host agreement with official NAM Core for silence, impulse, noise and
  sine; exact block-partition/reset agreement.
- Guarded wrapper tests, independent instances, bypass, mute and gain checks pass.
- Final binary tables, all ten audio table relocations and parameter init pass.
- A separate 0.11 delayed-identity build of this kernel passes independent
  history tests (maximum error below 4.4e-6); it is kept out of dist.

Build:

```sh
python3 src/hardware_probes/namlite/build_compact.py /path/to/Megaphone.nam --block --version 0.10 --output build/probes/namlite/block-0.10
python3 tools/nam_prototype/validate.py build/probes/namlite/block-0.10 /tmp/ms-nam-core
python3 src/hardware_probes/namlite/validate_host.py --build build/probes/namlite/block-0.10
python3 tools/nam_prototype/validate_binary.py build/probes/namlite/block-0.10
```

Install `dist/NAMLite.ZDL` and confirm version 0.10. Test alone with Input 50,
Output 25, Mix 100; compare against Mix 0 after warmup settles. The deliberate
144 ms diagnostic delay is removed. Listen for whether the persistent
bitcrushed texture remains, and report audio/UI stability. No hardware write
was performed here. Native 44.1 kHz execution of the 48 kHz model, with no
resampler, remains a fidelity limitation. Earlier test binaries are preserved.


## Marlboro Smokey Amp 0.12 (current local dist; hardware pending)

The user reports 0.10 "seems better"; disappearance of the bitcrushed texture
and remaining latency are not yet confirmed. At their request, 0.12 embeds
Marlboro Smokey Amp, modeled by drprophecystudio (TONE3000 metadata: crunch).
The compatible 48 kHz Lite submodel has three channels and 1,871 weights.
Processing and controls remain identical to 0.10; only capture and version change.
0.11 is reserved for the separate history diagnostic.

Source SHA-256: `cacb7da6a986b8e47c1ba37ea1953267291ae53aad005195f01418dfab9a1433`.
ZDL SHA-256: `06677004a5ea0a22114c6ba8ac4b0a9e09b38e3f966452f0721d3e978ab2e7ac`.
Size: 18,294 bytes, including 5,344 audio bytes. State: 133,360 bytes plus
alignment padding. Exact official NAM Core comparison, block/reset, guarded
wrapper and final binary checks pass. Hardware fidelity remains unverified;
the 48 kHz model still runs at 44.1 kHz without resampling.

Install dist/NAMLite.ZDL, confirm 0.12, and test alone at Input 50 / Output 25 /
Mix 100. Compare Mix 0 and lower Input to reduce drive. Megaphone 0.10 remains
at build/probes/namlite/block-0.10/NAMLite.ZDL. The original capture remains
outside the repository. This build is a local test, not a published release.
