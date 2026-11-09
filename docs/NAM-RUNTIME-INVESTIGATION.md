# NAM runtime investigation — 2026-09-25

**No confirmed root cause or new fix.** The converter remains on its existing
engine. The unsuccessful 0.15 trial is not promoted.

## New evidence: execute the actual ZDL

Used Ziddle's C674x interpreter from source archive
`https://berbasoft.com/ziddle/ziddle-source-1787802520.zip` with the checked-in
`tools/emulator/src/bin/namcheck.rs` harness. Tested the supplied
`NAMLite-amptrec.ZDL`, SHA256
`9d445680e567673cd9bbead290e090aa49c1f258f5456ef62a27e73f76e47890`.
The 16,384-sample mono test is silence for initialization/warmup followed by
220 Hz plus seeded low-level noise. Controls44/27/100, stereo input duplicated.
It exercises ring wrapping after initialization. The reference is the same
capture's host wrapper, including drive/mix/output smoothing.

- Init and edit handlers complete, with zero unimplemented instructions.
- Runtime controls reach approximately0.44/0.27/1 as intended.
- Actual machine-code output differs from the host wrapper by at most
  8.94e-8. This is float rounding, not a reproduced bitcrush fault.
- Current engine:18,612 emulated cycles per eight-sample callback.
- Speed trial0.15:17,996 cycles, **3.31% overall reduction**. The previously
  quoted8.3% applied only to its inner MAC loop.
- Current ideal arithmetic demand:102.6million emulated cycles/second at44.1kHz.
  This is not measured pedal utilization or a deadline guarantee. Cache/memory
  stalls, interrupts and the actual host scheduler are not represented faithfully.

Logs, raw float output and report: `build/probes/namlite/machine-audit/`.
The host uses knob values directly; the interpreter uses firmware-style edit
handlers, explaining a few ULPs of control/output differences.

## Why overload alone is not established

The older0.07 identity model was reported clean;0.09's delayed identity was
reported delayed and bitcrushed. Those binaries share audio instructions,
layout, loop counts and memory allocation, with different weights. Both now
measure25,156 emulated cycles/callback—more than the current crackling engine.

This is important counterevidence to an instruction-count-only explanation.
It does not exclude missed real-time deadlines, data-dependent hardware effects,
or a changed patch/setup. It does require keeping history-dependent runtime
behaviour in the investigation instead of treating overload as proven.
The current user report remains: direct recording, NAM alone, more artifacts
when adding other effects, no audible improvement with0.15.

## What is and is not ruled out

| Area | Evidence / remaining uncertainty |
|---|---|
| Incorrect capture export | All1871 weights match the supported source Lite model; no mismatch found. |
| Generated network math | Host agrees with NAM Core; actual target instructions agree with host on the exercised input. |
| Host buffer layout | Eight planar L/R samples and in-place ctx[5] agree with stock disassembly and prior clean diagnostics. |
| DSP deadlines / physical memory | Still open. Emulator cycles exclude physical cache/memory stalls and firmware interference. |
| History-buffer corruption or lifecycle | Still open on hardware. Guarded host tests and emulator pass; earlier delayed-identity result implicates history-dependent behaviour. |
| Clipping | Delivered recording is below full scale; steady test levels do not hit output limiter. This does not exclude earlier/transient clipping. |
| Capture sample rate |48kHz model runs at44.1kHz without conversion. Known fidelity limitation, but cannot explain the old delayed-identity corruption by itself. |
| Original large IR freeze | Load-only also froze; separate failure and not evidence proving NAM overload. |

## Next discriminating work

1. Test a lightweight integrity check across the same per-instance history arena:
   distinguish bad retained data from expensive neural processing. Do not repeat
   the already-passed simple dry/identity test as if it were new evidence.
2. Measure real callback execution/arrival timing, rather than infer headroom
   from compiler scheduling or desktop throughput. Confirm any timer reads work
   without changing firmware clock/cache configuration.
3. If retained history is sound but deadlines fail, optimize memory traffic and
   total callback work. If history fails even without the network, investigate
   the arena contract/lifecycle first. Another capture will not isolate this.

No additional hardware diagnostic is installed or released by this investigation.


## History integrity diagnostic ready

`dist/NAMMem.ZDL`, separateFXID909/version0.01; PE lists NAMMem under Delay.
Checks133360bytes using32 volatile pattern reads/writes per callback. Initial
fill followed by rotating indexed patterns catches stale or corrupted data;
failure latches until Test0→1. Quiet two-beep groups indicate completed passing
sweeps, four beeps indicate mismatches. Persistent single beep or no tone is
inconclusive. No neural processing and no hardware clock/register changes.
Guards,4-alignment, independent instances, injected corruption, pulse counts,
reset/bypass tests pass on host. Actual ZDL passes emulator init/edit/instruction
checks over12500callbacks; max898 emulated cycles versus18612 for current NAM.
This checks the same footprint but not identical history access patterns/load.
A pass narrows the investigation, not proof that all NAM history is safe.
Hardware result pending. Build/validate scripts in src/hardware_probes/nam_memory.


### Diagnostic correction0.02

User selected0.01 and heard no beeps. Reproduction using legal raw Test1 shows
params[5]=0.01 because the LineSel-derived handler divides by100. The probe
incorrectly checked0.5; its earlier emulator test used invalid raw100 and host
test seeded1.0. This was a diagnostic bug, not evidence about NAM memory.
0.02 checks0.005, host tests seed0.01, and validate_target.py verifies actual
ZDL Test0 silence and Test1 exactly two passing pulses after initialization.
Corrected0.02 replaces dist/NAMMem.ZDL. Hardware result pending.


### Hardware result: NAMMem0.02 passes

User reports working with two beeps repeating. The lightweight probe repeatedly
verifies its entire133360-byte footprint without latched mismatches. Basic arena
retention under this access pattern/load now has positive hardware evidence.
This does not prove the neural kernel's strided accesses, cache/interrupt
behaviour, or deadlines. Next investigation: measure callback timing during the
real neural kernel, rather than repeat the memory test or another capture.


### NAMTime0.01: actual capture timing diagnostic ready

Separate Delay effect FXID910 in dist/NAMTime.ZDL uses the original TREC
capture with defaults44/27/100. Read-only TSCL calibration over4096 dry
callbacks precedes warm-up and4096 measured neural callbacks. It then parks
the network and alternates low-pitch average / high-pitch peak beep groups.
Codes1=timer unavailable,2=below50%,3=50–80%,4=80–100%,5=at least100%
of calibrated callback interval. These are elapsed core-call ratios, not total
pedal CPU utilization; code-layout changes and interrupts remain caveats.
Host timer rollover/threshold/reporting/guard/reset checks pass. Binary audit
checks exact coefficient tables, ten address relocations and control init.
Target emulator accepts all instructions and runs the stopped-timer path
(its TSCL remains zero); this does not validate the measured neural path.
File20270bytes, audio6848bytes, state133404bytes. SHA256:
2dba6c756fa7c554fe6e73c199ab735918939d2902bd876ba932c77faff9ebfd.
Hardware timing results pending. NAMMem0.02 remains a confirmed hardware pass.


### Hardware result: NAMTime0.01 reports 5 low / 5 high

On 2026-09-25 the user reports a quick noise when enabled, followed by
alternating five low and five high beeps. Both average and peak elapsed core
measurements therefore meet or exceed the calibrated low-load callback interval.
Together with NAMMem0.02 passing, this makes a real-time deadline problem the
leading explanation for the crackling. It does not isolate arithmetic cost,
memory stalls or interrupt/scheduling overhead, and it does not give the exact
overrun ratio. The instrumented kernel differs in code layout from production.
The initial noise occurs before reporting parks the network; it is consistent
with the measurement phase, not separately proven to be an initialization bug.

Next work should reduce measured runtime cost, with coefficient/output parity
checks and the same hardware timing comparison. Do not promote the ineffective
0.15 unroll trial or switch captures as a purported fix. Preserve native-rate
model behavior first; lowering inference rate or simplifying the network is a
separate sound-changing fallback, not a transparent optimization.


### 2026-09-25: full-rate optimization screening and trial0.16

TREC and Marlboro both parse as the same23-layer,3-channel A2 Lite geometry
with1871 weights and48kHz source rate. Amp+cab capture content does not add
a separate cabinet convolution to this engine. Their fixed neural workload
is the same; learned weights differ. The existing native44.1kHz/48kHz model
rate mismatch remains a separate limitation.

Screened temporary-local storage, sample-major accumulation, fixed-tap loop
expansion, merged loop/finalization and paired-tap accumulation. Tested target
callback cycles versus original18612: local19803; sample-local27252;
fixed-tap26228; split fixed-tap30878; fused18360; paired17279; paired plus
sample unroll17685. Flat loop compiler schedule worsened to20-cycle initiation
interval and was not target-tested. Reassociation scheduling showed no useful
change and was not promoted. The source builder is
`tools/nam_prototype/build_optimization_trial.py`; private outputs live under
`build/probes/namlite/opt-*`. Full screening results saved to
`build/probes/namlite/optimization-screening.json`.

Selected paired taps for experimental NAMLite-amptrec0.16 in dist, sameFXID900.
No rate reduction, coefficient change, added buffering or changed sample
accumulation order. Host silence/impulse/noise/sine outputs match NAM Core
exactly and pass block/reset comparisons. Actual TI instruction emulation
passes init/edit/opcode checks and matches wrapper reference within8.95e-8.
Tables,8 relocations and init handlers pass binary audit.
19418byteZDL,6016byteaudio; SHA256:
4a61641026c40f9769996626dd75ede1740bb8ca1c8a2819352677a5fd286bea.

The7.16% emulated whole-callback reduction is modest (about4% versus failed
0.15) and excludes actual cache/memory/interrupt effects. Hardware result is
pending; this is not a claimed fix. Converter remains0.14 and baselineNAMLite
is untouched. NAMTime0.01 still measures the original kernel and must not be
used to judge0.16. Prior dist capture and PNG are backed up under the selected
trial's rollback-pre-0.16 directory.


### Review of reduced-rate changes (2026-09-25)

User reports the reduced-rate trial is crackle-free but distinctly narrower
and muffled. This supports insufficient real-time headroom as the leading
problem; it does not make reduced-rate processing sonically transparent.
No runtime, converter or dist binary was changed during this review.

Actual instruction emulation at44/27/100, same TREC coefficient/header data:
original8/8=18612 cycles; 0.16paired=17279; rate4of8=8937; rate7of8=18316.
Thus4/8 saves51.98%, but7/8 only1.59%, and is slower than the0.16 trial.
All init/edit/audio paths completed without unsupported instructions. These
are emulator costs, not physical pedal headroom. Neither code5 timing report
nor these results establish the comment's assertion that exactly2x is needed.

Findings in src/hardware_probes/namlite/namlite.c:
- Lines122–124 use floor(8*i/N) then average adjacent samples. AtN7 the
  sample centers are0.5,1.5,...,6.5, then8.5: spacing is nonuniform. The output
  interpolator assumes uniform spacing. The resulting periodic time error
  creates sidebands, even for an identity network. N5/N6 have similar issues.
- The two-tap averaging and linear interpolation are not a proper anti-alias/
  reconstruction filter. The isolated unity-network experiment shows an8kHz
  sine loses4.48dB at4/8,3.11dB at7/8. At7/8 it also creates a2.4875kHz spur
  at-16.01dB relative to the input. A16kHz sine at4/8 aliases to6.05kHz at
  -9.25dB. These are conversion-only measurements, not NAM response estimates.
  The claim that dullness is NOT due to resampling is therefore too broad.
- Lower model rate also changes the capture itself:22.05kHz at4/8 and
  38.5875kHz at7/8 versus48kHz training. Both spectral/dynamic behavior and
  conversion filtering contribute; band-energy measurements alone do not
  establish perceptual transparency or model accuracy.
- Warm-up counts8192 output samples, not neural steps. N4 warms4096 steps,
  N5 warms5120 and N6 warms6144, all short of the6347-sample receptive field.
  Startup can therefore expose unsettled model history. N7 warms7168.
- `validate_host.py` does not define NAM_RATE_STEPS, so invoking that existing
  test unchanged exercises the full-rate path, not the new conversion path.

Keep the half-rate result as evidence, not a fidelity-preserving release.
Next work: proper continuous rational resampling with anti-alias/reconstruction
filtering, neural-step warm-up, and measured whole-callback timing for each rate;
compare at matched loudness with the48kHz NAM reference. Such resampling will
not itself restore the dynamics of a48kHz model executed at22.05kHz. If adequate
headroom requires half rate, a smaller full-rate model/distillation is the
more faithful long-term direction. Existing converter remains untouched.

Reproduction: tools/nam_prototype/review_rate_trial.py; conversion/timing reports
and target logs: build/probes/namlite/rate-review/.


### Hardware result: 6/8 trial has no reported bitcrushing

User reports "NAM-6of8 uploaded to pedal, no bitcrushing." This is positive
hardware evidence for a cleaner reduced-rate setting above4/8. Tonal fidelity
and operation alongside other active effects were not reported in this test;
neither is established by this result. The known input spacing, filtering and
warm-up review findings still apply. No binary changed for this report.

Follow-up: user says6/8 is "Brighter, but still somewhat muffled." It is a
useful crackle-free baseline, not a confirmed tonal match. Actual target
emulation measured14683 cycles/callback versus18612 full-rate (21.1% less),
with no unsupported instructions or init/edit errors. This timing is not
physical hardware headroom and does not establish multi-effect stability.


### 2026-09-25: NAMProf 0.01 hardware result — memory-bound, and the working set is fixable

`NAMProf` (FXID 911, `src/hardware_probes/nam_profile/`) timed the same
full-rate TREC kernel as NAMTime and reported placement, decoded from a direct
recording with `tools/decode_namprof.py` (sync and XOR checksum valid):

| word | value |
|---|---|
| model min / avg / peak | 32,333 / 37,510 / 51,231 cycles |
| emulated, same code | 18,612 cycles |
| arena | 0xC022D000–0xC02D9440 (705,600 B), DDR, **MAR = 1 (cacheable)** |
| weights | 0xC0202AB8, DDR, cacheable |
| ctx | 0x11F03000 — L1D SRAM |
| live cache config | L1D 16 KB, L2 128 KB (matches the static firmware reading) |

**Memory stalls are real and structural.** The C674x is statically scheduled,
so real minus emulated is stall time: 13,721 cycles (42%) even in the *fastest*
of 4,096 callbacks, 18,898 (50%) on average. The uncached-DDR worst case is
ruled out — the arena is in the cacheable first 16 MB.

**Cause: the working set just overflows L2.** History rings are rounded up to
powers of two: 129.8 KB of history + 7.3 KB of weights = 137 KB against a
128 KB L2. Sized exactly, history is 77.3 KB and the working set 84.6 KB —
well inside L2. The worst offenders: dilation 101 needs 513 floats and gets
1,024; dilation 239 needs 1,203 and gets 2,048. Exact sizing needs a non-mask
wrap (compare-and-subtract; `%` is banned), costing a couple of ops per load
address against DDR misses. Output is unchanged — same maths, different layout.

**The `period` word is NOT the callback budget, and NAMTime overstated the
overrun.** NAMProf measured 10,724 counter ticks between callbacks — a 59 MHz
clock at face value, implausible for a C674x — and taken as budget it puts the
model at 350% on average. That cannot be right: 6/8 rate does 79% of the work
and plays clean on hardware. The counter evidently does not advance in
wall-clock time between callbacks; most likely it pauses while the CPU idles,
making `period` the *work* done per callback outside the model, not the time
available. Fitting the hardware observations (full rate crackles at peaks,
6/8 clean) puts real capacity at roughly 51–62k cycles per callback, i.e. a
~280–340 MHz clock; a standard 300 MHz C674x fits exactly. NAMTime 0.01 used
the same calibration, so its "code 5" was directionally right but the
magnitude is not meaningful. Only same-context ratios (real vs emulated model
cycles) are trustworthy from these probes.

Next: full-rate build with exactly sized rings. Expected to remove most of the
13.7–18.9k stall cycles; that would put full-rate peaks near NAM6's measured
clean envelope.


### 2026-09-25: exact-ring full-rate build (NAMFull 0.19) and NAMProf2

`tools/nam_prototype/exact_rings.py` rewrites a generate_block kernel so every
history ring is exactly `(k-1)*d + 8` floats instead of the next power of two:
history 129.8 KB → 79.1 KB, working set ~86 KB against the 128 KB L2.
`validate_exact_rings.py` requires **bit-identical** output against the
power-of-two kernel (8-sample blocks, ragged blocks 1..8, reset mid-stream) and
checks a per-layer range guard. Build: `build_halfrate_trial.py --steps 8
--exact-rings`.

**Design rule learned the hard way: no data-dependent condition inside any
loop body.** The first version wrapped each index with `if (q >= n) q -= n`
inside the sample loops. Host: bit-exact. TI build in the emulator: output grew
every callback until the wrapper's range check reset it (~every 14 callbacks),
though every ring stayed finite and in range — the reads were fetching real
samples from the wrong time. Built with `-mu` (no software pipelining; note the
flag is `--disable_software_pipeline`, and a misspelling is silently ignored)
it was correct. So the software-pipelined form of loops whose wrap predicate
changes per iteration is wrong in TI's pipeliner or in Ziddle's SPLOOP model;
which one is not established. Because a TI miscompile could write outside a
ring on hardware (a freeze), that shape was abandoned, not flashed.

The shipped design has no such predicates: each plane carries an 8-float
mirror (`h[n..n+7] == h[0..7]`) so a tap's 8 reads run into it instead of
wrapping, with one scalar wrap per tap outside the loop; writes are split into
at most two loops with precomputed bounds, then the mirror is refreshed. TI
build: emulator output matches the power-of-two build within 3e-7, no resets;
`tools/emulator` `namstate` checks positions, finiteness and the mirror
invariant after every callback. Relocation profile identical to the
power-of-two build (24: ABS32 ×10, ABS_L16/H16 ×7).

Cost: 22,040 emulated cycles vs 18,612 (+18%, for the split writes and mirror
refresh). The bet is the memory saving: on hardware the power-of-two kernel
stalled 13.7k (min) to 18.9k (avg) cycles per callback. `NAMProf2` (FXID 912)
measures this exact kernel on the pedal; decode with
`tools/decode_namprof.py rec.wav --emulated 22040`. `NAMFull` (FXID 903) is the
playable build. Both staged in dist/ (git-ignored). Hardware results pending.


### 2026-09-25: NAMProf2 hardware result, then NAMFull2 0.20 / NAMProf3

NAMFull 0.19 still crackles. NAMProf2 (same exact-ring kernel) on the pedal:

| | power-of-two (NAMProf) | exact rings (NAMProf2) |
|---|---|---|
| emulated | 18,612 | 22,040 |
| real min / avg / peak | 32,333 / 37,510 / 51,231 | 31,497 / 34,464 / 43,444 |
| stall avg (real − emulated) | 18,898 | **12,424 (−34%)** |

Fitting L2 cut the stall by a third, but +3,428 cycles of added work (split
writes, unconditional mirror refresh) gave much of it back: average −8%, peak
−15%. NAM6 plays clean at ~79% of the power-of-two work, i.e. an estimated peak
of ~40k; this is ~43k, so the remaining gap is roughly 7–10%.

Two further layout-only changes, both bit-identical on the host
(`validate_exact_rings.py` now checks both layouts) and clean in the emulator
(`namstate ... il` checks the interleaved mirror):

1. Mirror refreshed only when a block writes slots 0..7 (`base < 8` or the
   write wrapped) — a scalar test outside the loop, so the no-predicate rule
   holds. Emulated 22,040 → 20,362.
2. Channels interleaved per slot (`h[3q+ch]`) instead of three planes, so a
   tap's 8-sample window spans ~2 cache lines instead of 3. The residual
   stall is L1D (16 KB) misses served from L2, so fewer lines per read should
   cut it; it also made the reads cheaper: emulated 20,362 → **19,666**
   (+1,054 over the original's arithmetic, down from +3,428).

`NAMFull2` (FXID 904, `NAM-full2`, 0.20) is the playable build; `NAMProf3`
(FXID 913) measures it — decode with `--emulated 19666`. Relocation profile
unchanged (24). Hardware results pending.


### Independent review of NAMProf/cache proposal and exact-ring proof

The reported placement/cache data makes a tighter history layout a strong
full-rate candidate, but the cache-capacity explanation is not yet proven.
Current history alone132864bytes; history plus1871floatweights140348bytes
(137.06KiB). Exact-capacity planar rings with the same two-float plane padding
use79140bytehistory; with weights86624bytes (84.59KiB). Scratch, cursors,
code, firmware and other effects are additional cache consumers. Fitting a
nominal capacity does not exclude conflict misses; see TI SPRUG82A section3.3.

Added an experimental generator (not a converter/release change):
tools/nam_prototype/generate_exact_rings.py. It uses per-layer cursors and
single conditional wrap corrections, preserving arithmetic order and rate.
Caller must initialize cursors via NAM_RESET_RINGS; no runtime wrapper has
been switched to this layout. Generated private files:
build/probes/namlite/exact-rings-review/. Host tests against upstream NAM Core
are bit-exact for silence, impulse, noise and sine across16384samples and
8/257-frame processing partitions. This verifies those vectors, not a universal
proof or pedal-speed result. No exact-ring ZDL published or installed.

Cautions about earlier timing interpretation: The reported10724 dry-period
value must not be treated as a verified wall-clock callback budget. The
claimed idle pause/300MHz clock and51–62k capacity remain hypotheses, not
measurements. My earlier claim that five beeps established actual deadline
overrun was too strong; it established only a ratio to that dry calibration.
Reduced-rate hardware results still support a workload-related problem.

Also, NAMProf is not machine-code-identical to standalone NAMLite: running the
actual profiler binary in the emulator gives20076cycles for measured-phase
callbacks versus18612 standalone. The profiler inlining/instrumentation changes
code scheduling. Thus subtracting18612 to label all excess hardware timing as
memory stalls is not a precise isolation. Cache delays remain plausible, but
interrupts and profiler differences must be separated or bounded before giving
a stall percentage. Raw direct recording was not re-decoded in this review;
hardware words were read from the existing investigation notes.


### 2026-09-28: tone stack (NAMEQ 0.21, FXID 905)

Owner report on NAMFull2: works, but riding the edge — one fuzz before it
fits with an occasional crackle; two more stock blocks don't.

Bass / Mid / Treb added as knobs 4–6 (`--tone-stack`), voiced like the NAM
plugin's `BasicNamToneStack`: bass low shelf 150 Hz ±20 dB, middle peak
425 Hz ±15 dB (Q 1.5 cut / 0.7 boost), treble high shelf 1.8 kHz ±10 dB,
RBJ biquads in the plugin's order. Coefficients are computed exactly at build
time for every knob position (`tools/nam_prototype/tone_stack.py`, 3×101×5
floats) — no runtime trig, which the loader cannot resolve. Knob 50 is an exact
identity, so a flat EQ is bit-identical to NAMFull2, on the host and on the TI
build. `validate_tone_stack.py`: float filter within 0.004 dB of the double
reference; Treb 90 measured +7.9 dB through the whole wrapper (design +8.0).
(A first measurement said +1.9 dB — an unwindowed FFT, where leakage from the
low notes swamps a cab-simulated amp's few high bins.)

Cost **+345 cycles (~1.8%)**, independent of settings. The EQ is one combined
8-sample loop after the network, with the ±16 range check folded in
branch-free and run *before* the EQ (a +20 dB boost must not look like a
diverged network). Measured alternatives: per-band loops that skip untouched
bands were worse whenever the EQ is used (+461 treble-only, +790 all three),
because separate loops cannot overlap the recursive filters.

**Second instance of the pipelining hazard.** Removing the old range check
from the per-sample output loop also removed its early return — which had been
keeping that loop out of software pipelining. Its body has per-sample
predicates (warm-up counter, clip), so it became the same shape that failed in
the exact-ring work: host still bit-identical, TI build off by up to 0.09 with a
flat EQ. An early-return NaN/∞ guard (±1e4, unreachable by the EQ) restores the
loop's original shape and bit-identity. Lesson: an early return can be
load-bearing; check SPLOOP counts when restructuring loops, and compare the TI
build, not just the host.

PE: NAM slots are rebuilt from 3-knob templates, which hid Bass/Mid/Treb.
`extract_effect_db.py` now takes a staged dist/ build's knob list for its slot.

### 2026-09-28: register-accumulated taps (engine 0.22)

Hardware report on 0.21: works, but only one stock effect (Great Muff) fits
beside it and the chain rides the edge. The tap loop was the target: SPLOOP
scheduled it at ii=5 with 6 stages, but each layer's loop runs only 8
iterations (one per sample of the block), so ~40% of every loop is prologue and
epilogue, and that loop runs once per tap (156 times per callback).

`exact_rings.transform(..., regacc=True)` turns it inside out for the common
8-sample block: the tap loop is outer, samples are inner and fully unrolled,
and the 3 channels x N samples of output live in registers until the last tap.
The ring index is computed once per tap with a branch-free wrap
(`x + (n & (x >> 31))`), so the loop body stays predicate-free (see
SAFE-DSP-RULES: data-dependent predicates inside pipelined loops are the
known TI miscompile/mis-emulation hazard). Ragged blocks (count != 8) keep
the original loop.

- **8 samples at once (24 accumulators): rejected.** Register pressure spilled;
  43,637 cycles, and the TI output diverged from the host by 0.19 (root cause
  not chased once the design was abandoned).
- **Groups of 4 (12 accumulators, two passes over the taps): shipped.** Tap
  loops pipeline at ii=19 (the resource bound, 3 iterations in flight).
  Emulated callback min/median/max 15,104 / 15,763 / 17,367 vs 20,011 median
  for 0.21 (-21%). Output bit-identical to 0.21 on the TI build at EQ flat,
  90/20/70 and 0/100/0; host validator +regacc 0.0 in every case; namstate
  clean; 0 resets; relocations 27 (0.21: 29).

Emulated cycles exclude memory stalls, which NAMProf showed are a large share
on hardware, so the real saving is not guaranteed to be the full 21%; the
working set is unchanged, so stalls should not grow. Packaged as loader engine
0.22; capture 1 rebuilt through the loader (byte-identical to a direct build).
0.21 templates and capture 1 archived under `build/nam-archive/2026-09-28/`.

### 2026-09-28: noise gate (engine 0.23) and capture 2

Hardware report on 0.22: "seems much better", but steady noise from the
effect. The recording (no playing, Input 100 / Bass 75) is a steady -40 dB
floor: a 134 Hz resonance plus hiss peaking at 3-4 kHz and gone above 5 kHz --
the capture's own amp/cab voice. The emulator reproduces it from -76 dB of
white noise at the input (-44 dBFS out), and gives silence for silence, so it
is the capture amplifying input hiss (~35 dB of gain), not the engine.

Gate (`nam_gate.h`, `-DNAM_GATE`, knob 7): detection on the raw mono input,
gain applied to the model output through the existing `net.gain[]` (after the
tone stack), like the NAM plugin. All gate logic is scalar per callback; the
only new loop is a predicate-free sum of squares (ii=4). Envelope: fast rise,
~10 ms fall; open above threshold, stay open to 6 dB below (hysteresis) plus a
30 ms hold; gain to 1 in ~0.5 ms, to 0 over ~50 ms, snapped to exactly 1 / 0.
Threshold -100 + 0.7 x knob dB (power table, no logf/powf helpers).

- Gate 0: bit-identical to 0.22 in the emulator (EQ flat, 90/20/70).
- Gate on: TI emulator vs host build 1.2e-10 (same as the ungated baseline).
- Emulated cost +170 cycles (15,933 / 15,950 median, off / on). The input loop
  went ii 49 -> 53; the tap loops are untouched (ii=19).
- With -76 dB hiss, Gate 30/40 stay open, 50/60 close: hiss falls from -41 to
  -173 dBFS within ~0.7 s of the last note; notes bit-identical to ungated
  after the ~4 ms opening ramp.

Capture 2: "Marlboro Smokey Amp" (TONE3000, crunch), the A2 Lite submodel of a
SlimmableContainer, made through the loader's `convertNamed` into slot 2 (FXID
901). Its emulator output equals a direct build's exactly. At the same knobs it
is brighter (spectral centroid ~2.1 kHz vs ~1.1 kHz), leaner in the lows and
more dynamic (crest 12 vs 8.5 dB) than amptrec.


**Hardware: 0.23 froze on boot** ("never fully loads"), both 0.23 files installed
(amptrec slot 1 and smokey slot 2) and the saved patch holding amptrec. Static
review found nothing: `_init`, all 8 edit handlers (Gate = knob id 8, params
offset 44) and relocation shapes match known-good 8/9-knob customs; matcheck,
namcheck and namstate pass. Candidates: (1) slot-2 template (never booted on
hardware before), (2) the 7-knob layout meeting a patch saved with 6 knobs,
(3) the gate code. Bisect files, all in `dist/` with distinct FXIDs so they install together:
`NAMLite-smokey` (901) = 0.22 engine in the slot-2 template; `NAMLite-t7knob`
(920) = 7 knobs, gate compiled out (`--undefine=NAM_GATE`, output bit-identical
to 0.22); `NAMLite-tsize` (921) = 0.22 padded with 2 KB of dead `.const`
(`-DNAM_PAD_FLOATS=500`) to text+const 29,576 B, above 0.23's 29,336 (largest
NAM that booted: 0.22 at 27,536; output bit-identical). Loader reverted to the
0.22 templates meanwhile.

**Bisect result (2026-09-29): the engine is innocent.** Each file booted and
played alone on hardware: `t7knob` (7 knobs, no gate), `tsize` (0.22 padded
past 0.23's size), `smokey` (0.22 engine, slot-2 template) and `tgate` (FXID
922, `.text` byte-identical to the 0.23 that froze; Gate knob works). The pedal
kept freezing on boot after the 0.23 files were gone while four 0.22-engine NAM
files were installed together, and the original freeze had two installed. So
the trigger is several NAM files installed at once (each ~30 KB, ~15 KB of it
`.const` weights/tables -- far above any other custom). A duplicate-FXID theory
(old trials used 901-905) was ruled out from the ZEM list. Pending: two NAM
files installed together to confirm, then find the limit. Loader back on 0.23;
bisect files in `build/nam-archive/2026-09-28/freeze-bisect/`.

**Cause found (2026-09-29): filename truncation, a documented rule the loader
broke.** Two NAM files installed together froze on boot (confirmed). The
pedal keeps 8 characters of a ZDL basename and freezes on boot when two
installed files share the cut-down name (SAFE-DSP-RULES.md, README "Identity
and packaging"). Every loader file was `NAMLite-<name>.ZDL` -> `NAMLite-`. The
trial builds (NAM5, NAM6, NAMFull2, NAMEQ...) had short distinct names and
coexisted, which is why the engine, the shared `Fx_FLT_NAMLite` symbols and the
slot-2 template all looked guilty in turn but were not. Fix: the loader names
files `NAM<slot><first 4 of name>.ZDL` (<= 8 chars, unique per slot; tests
assert it), PE reads the full embedded `NAM-<name>` instead of the filename, and
`build/extract_effect_db.py` now refuses to run if any dist/ basename is over 8
characters or collides. dist/: `NAM1ampt.ZDL`, `NAM2smok.ZDL` (bytes unchanged).

**Hardware 2026-09-29:** with the renamed files, both captures installed together boot fine; gate works.

### 2026-09-30: NAM + CabIR crackles -> engine 0.24 and CabIR trim

Hardware: NAM (0.23) + CabIR 0.20 crackle together; each alone is fine. Pair
cost was 15,950 + 950 emulated cycles.

- CabIR: the 8-biquad cascade back in ONE pass with every state in a local
  (0.10's memory-state version never pipelined): 950 -> 872, bit-exact.
- NAM 0.24 (`-DNAM_FAST_IO`): once warm (>= 8192 samples), the input loop
  (serial, ii 53, clip + warm-up predicates) and the output loop (serial by
  design: early return + predicates) get predicate-free twins -- clip as
  (|v+1|-|v-1|)/2 via ABSSP, range check left to the branch-free pre-EQ flag.
  Input loop now ii 12 with 3 in flight. 15,950 -> 15,311 (-4%). Output vs
  0.23 87-91 dB below signal (clip rounding); TI vs host 1.2e-10; namstate
  clean. Warm-up path unchanged.
- Pair now 16,183 vs 16,900 (-717). Where NAM's time still goes: the tap loops
  are at the M-unit bound (2 MPYSP/cycle, ii 19 for 36 MACs), but each runs
  only 6 taps, so SPLOOP fill/drain is ~30% of them. Next lever if needed:
  generate per-layer straight-line tap code (k known at build time).

**Hardware: 0.24 set froze on load** (NAM1ampt/NAM2smok 0.24 + CabIR one-pass).
0.24 is the largest effect ever loaded: text+const 30,336 B (largest that
booted: tsize 29,576; 0.23 29,312; HYBRID IR documents a conservative
28,904 B code+const cap for its template). Suspects: a load-size cap between
29,576 and 30,336, the 0.24 code, or the new CabIR. Loader reverted to 0.23;
dist/ back to the booted 0.23 captures; 0.24 kept in
build/nam-archive/2026-09-28/*-0.24-FREEZE/. Bisect: CabIR (new) with 0.23
captures, then `dist/TSize2.ZDL` (FXID 921) = 0.23 padded to 30,512 B,
output bit-identical to 0.23 -- if it freezes, the cap is real.

**Size cap confirmed (2026-10-02).** NAM 0.23 + new CabIR booted (CabIR fine;
the NAM + Cab crackle persists: recording shows ~4 HF dropout bursts/s,
clustered 15-45 ms apart = missed callback deadlines). TSize2 (0.23 + dead
data, 30,512 code+data) froze when selected -> size cap, not 0.24's code.
0.24b: warm-up and steady state share ONE predicate-free input loop and ONE
output loop (warm-up zeroing is a per-callback mask; mix target 0 until warm
keeps warm-up exactly dry). 31,766 B, code+data 29,152 -- smaller than 0.23.
Host: vs 0.23 87-117 dB below signal after warm-up; warm-up exactly dry.
Emulator checks pending (the Ziddle checkout in /tmp was wiped).
Emulator (Ziddle re-installed in ~/ziddle): 0.24b 15,277 vs 0.23 15,950 median
(-673; 0.24 was 15,311); TI vs host <= 1.2e-7; namstate clean; matcheck
PASS. Packaged as loader engine 0.24 (size guard passes); dist/ NAM1ampt and
NAM2smok rebuilt (capture 1 byte-identical to the direct build).

### 2026-10-02: 0.24b "better, still a tiny bit of crackling" -> 0.25 + Eco

Tried and rejected (emulated, flat EQ, 0.24b = 15,277):
- straight-line taps for the k=6 layers (one body for both 4-sample groups):
  32,765 cycles and over the size cap -- the list-scheduled straight-line code
  is far worse than the modulo-scheduled loop.
- activation fused into the tap groups (no zbuf round trip): 17,079, +1.7 KB.
- -O3 / --opt_for_speed=5: no change.
Kept:
- 51-row tone table (`tone_stack.write_table(half=True)`, NAM_TONE_STEP 2):
  3 KB smaller, same speed; even knobs bit-identical.
- flat-EQ skip (all three knobs 50): 15,148 (-130); bit-identical to 0.24b.
- CabIR: Reso+Pres both 50 -> 6-biquad loop: 833 (862 when used).
- Eco 7/8 (`NAM_RATE_STEPS=7` + a count==7 register-accumulator path):
  14,499 (-650 vs full). Loop overheads do not shrink with the sample count,
  so only ~4%. smokey Eco vs full: -0.3..-1 dB below 10 kHz, -2.1 above.
dist/: NAM1ampt 0.25 full rate (29,190 B), NAM2smok 0.25 Eco ("NAM-smokeco",
29,286 B). Loader: Eco checkbox -> tools/nam_template_eco/.

**Hardware (2026-10-02): NAM-smokeco (0.25 Eco) + CabIR -- no crackling.**
CabIR was 7-9 dB quiet (peak normalisation); now loudness-matched.

### 2026-10-03: last ticks -> Eco 6/8

Hardware: smokeco (7/8) + CabIR still ticked occasionally with Great Muff
(bypassed) in the patch and both EQs active. Owner's fix confirmed: NAM EQ at
50 (flat-EQ skip) + Great Muff removed -> no overload.
- Rejected: cab built into NAM (NAM_CAB, 9 biquads in the EQ pass + 32-tap
  FIR). Cab on 15,595 vs smokeco + CabIR 15,520; cab off +346; 34.5 KB, over
  the size cap. Code removed.
- Eco 6/8 (count==6 register-accumulator path): median 13,841 / p99 14,843 /
  max 15,501 vs 7/8 14,658 / 15,657 / 16,474. Through the SM57 cab model, vs
  full rate: within 0.7 dB in every band 100 Hz-8 kHz. TI vs host 3.9e-6 (EQ
  on), namstate clean, matcheck PASS. Eco templates are now 6/8; 7/8 archived.

### 2026-10-06: CabIR one-cab-per-effect (0.30) and 16 NAM slots

CabIR's bank + Cab knob replaced by 16 single-cab slot effects (FXID 930-945);
NAM capture slots extended to 16 (900-907, 950-957). Both template sets
re-packaged; slots 1-2 byte-identical to before (installed captures stay
valid). PE hides unnamed reserved NAM/CabIR slots unless a patch uses one.

### 2026-10-06: review suggestions measured (Eco grouping, EQ, gate) -- none kept

Emulated callback cycles, smokeco Eco 6/8, owner's settings (Mid 68 / Treb 66):
- Eco 6 samples as 4+2 (shipping): 13,841 median / 14,843 p99 / 15,501 max.
  2+2+2 15,229; one group of 6 26,966 (register spill); 3+3 16,042 and its TI
  output diverges from the host (0.21-0.31) -- same TI pipelining hazard class.
  `build_halfrate_trial.py --eco-group N` kept for future screens.
- EQ smoothing (one table row per callback toward the knob): +137..278 cycles.
- Run only the one EQ band in use: no gain at 2 active bands (+158 vs 0.25 with
  its check overhead); skip when settled-flat without clearing state: part of
  the same +141 restructure cost.
- Skip gate math at Gate 0: -59 vs restructure but TI output != host (1.6e-3).
All reverted; namlite.c audio code is byte-identical to the shipping 0.25.

**Hardware (2026-10-06): NAM-amptrec (full, cost 194) + Great Muff -- accepted,
no crackle.** Pedal DSP limit measured with pass-through cost probes: 224.4
accepted, 228.4 refused. Costs now: full 194 / Eco 7/8 188 / Eco 6/8 177 /
CabIR 10; PE meter budget 228. Declared cost, pedal admission and real load
agree on every chain tested so far.

### 2026-10-19: 16-bit taps trial (no-go), Eco 0.26 resampling, soft limiter

Emulated callback cycles, smokey (44.1 kHz), flat EQ, median. Builds from
`tools/nam_prototype/package_eq_templates.py` (engine 0.26, uncommitted
templates) and `tools/nam_prototype/q16_trial.py`.

**16-bit taps (q16_trial.py): not worth building.** The dilated convolutions
in int16 pairs with DOTP2 into 32-bit accumulators, the rest float. The tap
loop's core improves (ii 13 vs 19 per tap for 4 samples), but packing the
history (SPINT + SPACK2 per channel per sample) and converting back cost
more: whole NAMLite 17,008 vs 15,117, kernel alone 16,241 vs 14,589. On the
host the q16 kernel matches float to -74 dB, and on TI the bare kernel
matches its host build to -81 dB. A fully tuned version (DDOTP4, one
8-sample group) is projected at 10-20% saved, below the 25% bar. Inside
NAMLite the q16 network read an all-zero input: see the restrict finding
below.

**Eco 0.26: cubic, evenly spaced resampling** (`src/hardware_probes/namlite/nam_resample.h`).
0.25 sampled the input at floor(8i/N) (uneven) with a 2-tap average and
interpolated the output linearly. Identity-network model, 6/8, -6 dBFS
sine, worst spur:

| Tone | 0.25 | Even + linear | Cubic both ways (0.26) |
|---|---|---|---|
| 1 kHz | -33.5 dB | -41.6 dB | -79 dB |
| 3 kHz | -22.8 dB | -31.2 dB | -53 dB |
| 8 kHz | -11 dB | -18 dB | -24.5 dB |

The 0.26 version also keeps 2.8 dB more level at 8 kHz. Cost: Eco 6/8
14,013 vs 0.25's 13,682 (+331). TI vs host 4.7e-10.

**Soft output limiter (0.26):** exact below 0.75, then d*u/(1+u) toward
+-1 (no corner), replacing the hard clip at 1.0. It runs in its own loop,
because the mix loop cannot be pipelined (the mix ramp) and any work inside
it costs its full latency. Full rate 14,974 vs 15,117 (-143). TI vs host
4.7e-10 (flat EQ and Bass 68 / Mid 30 / Treb 66 / Gate 20).

**Restrict hazard (latent in the shipping engine).** The generated
`nam_block` declares `input`/`output` restrict. Once inlined into NAMLite,
the TI compiler may move its reads of `net.input` above stores made just
before the call, and stores into `net.output` past reads just after.
- Unrolled copy loops into `net.input` / out of `net.output` (Eco) gave TI
  output 0.26 away from the host. The same code as rolled loops is exact.
- The q16 network read zeros.
- 0.25 is exact only by the current schedule. Harden it: no restrict on
  those two pointers, or copy through the kernel's own arrays.

**Deeper Eco, measured (cubic resampling), each vs full rate in dB, pink noise:**

| Hz | 100 | 1k | 2k | 3k | 4k | 5k | 8k | 10k | Cycles |
|---|---|---|---|---|---|---|---|---|---|
| 6/8 | +0.3 | +0.3 | +0.2 | -0.3 | -2.3 | -4.2 | -3.1 | -6.5 | 14,013 |
| 5/8 | | | | | | | | | 13,540 (no fast count-5 path) |
| 4/8 | +0.3 | +0.5 | -0.3 | -4.6 | -7.5 | -8.0 | -13.6 | -15.3 | 10,978 (-27%) |

4/8 is the only real saving, and it changes the tone from 3 kHz up. A
per-capture correction EQ fitted in the loader (it now has the network,
`tools/nam_response.js`) could take most of the magnitude loss back.

### 2026-10-19: 48 kHz true rate: not feasible on this DSP (code removed)

Goal: play a 48 kHz capture at 48 kHz. That is 160 network steps per 147
input samples, so 8 or 9 steps per 8-sample callback (8.707 on average).

**What was built (uncommitted, removed).**
- The kernel generator took a `block` size: rings (k-1)*d + 9, a 9-slot
  mirror, I/O arrays of 10. At block 8 the output was byte-identical to
  today's kernel.
- Count 9 first used a 5+4 fast path, which made the file 33.9 KB, over the
  size the pedal loads. It then used one 4-sample body run at offsets 0 and
  4, plus a 1-sample tail.
- The resampler was cubic at exact rational positions (`ph` in 1/160 sample,
  output cycle position in 1/147). A Python model with an identity network
  showed: indices always in bounds with two steps to spare; level within
  0.5 dB to 8 kHz; spurs -80 dB at 100 Hz, -66 dB at 3 kHz, -36 dB at
  8 kHz; ~4 samples of latency.
- The block-9 kernel was bit-exact against `generate.py`'s reference with
  8/9 blocks, and TI matched host to 2e-9.

**Why it was dropped: cost.**

| Build | Median cycles | Max cycles |
|---|---|---|
| Full rate (0.26) | 14,974 | 16,578 |
| 48 kHz, ideal (x8.707/8) | ~16,300 | ~18,000 (declared ~215 of ~225) |
| 48 kHz, as built | 23,088 | 24,868 |
| 48 kHz layout run at a fixed 8 steps | 18,195 | |

- In the fixed-8 build, the resampler loops ran at ii 44 (aliasing, fixable).
- The 9th step costs a whole extra pass over the 23 layers for one sample
  (~4,900 cycles on the 70% of callbacks that need it).
- Even a perfect version would declare ~215 and leave nothing but a cab
  beside it. As built it is ~290.

**Tone-match EQ instead? Only partly.** Measured with `nam_response.js`,
"as trained" (the curve x48000/44100) against "on the pedal":
- An amp-only 48 kHz capture (smokey) is within ±1 dB, so there is nothing
  worth fixing.
- A capture with the cab built in (BRIT50 "CAB") is off by up to ±5 dB:
  -3 dB at 100 Hz, -5 dB at 2-3 kHz, +4 dB at 6-8 kHz. Its resonances move
  with the rate, and 3 or 4 fitted peaking filters still leave ±3-4 dB at
  2-3 kHz. A cab-style FIR fit (CabIR, ~10 DSP points) could follow it more
  closely.
- **Practical route:** use an amp-only 48 kHz capture plus CabIR. The cab
  loader resamples 48 kHz IRs properly, and the amp's own shift is small.

**Hardware (2026-10-19):** the 0.26 builds (full NAM210fu, Eco NAM211ec, Eco+
NAM212ec, all from Marlboro Smokey) and the split test (NAM7spli) all load
and play. The owner hears Eco+ as clearly worse than full rate; it stays as a
lower-DSP option.

### 2026-10-19: split outputs, and a Ziddle bug

**Split B.** One output gets the amp, the other the dry guitar, with knob 3 as
the dry side's level (-24..+24 dB). An earlier test (NAM7spli) used an 8th knob
for the side; a 9th would not fit the size cap, so the side is now chosen in
the loader and written into the file as two factors. A route NUMBER read with a
float->int conversion and compares worked too, but the factors need neither.

**The emulator said the amp side was silent; the pedal plays it.**
- Probing in Ziddle (a write watch on the arena plus a per-instruction trace of
  one callback): the soft-limiter loop loaded its `net.gain` pointer from a
  stack slot and got 1.0f instead, so it read "gain" from 0x3F800000 = 0.
- The slot was written by `STW.D2T1 A20,*B15[20]`, a 16-bit Dstk instruction
  under `SPMASK L1,L2,D2` in the prolog of the input loop's SPLOOP. Masked, it
  must run once. Ziddle ran it on all 8 iterations, with A20 already reused.
- Cause: Ziddle's `compact_unit` took Dstk's DATA side (bit 12) as its unit
  side, D1, so a D2 mask missed it. Dstk is always .D2. Fixed in the local
  Ziddle copy (`product/cpu/src/insn/mod.rs`).
- Why it came and went: any change to the state layout or code moved stack
  slots and registers, so the replayed store sometimes wrote the right pointer
  (harmless) and sometimes a float.
- The split build still differs from the host in the fixed emulator (amp side
  near silent, max diff ~0.2-0.3), but plays on the pedal. A second emulator gap
  of this kind is likely; not chased further. Removing `restrict` from the
  kernel's input/output pointers (tried first) changed nothing and was reverted.

