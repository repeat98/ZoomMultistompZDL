# NAM + CabIR DSP audit — 2026-10-06

Read-only runtime review; no production source, template or dist changes.
Reviewed current local uncommitted work, runtime investigation, loader notes,
NAM wrapper/tone/gate/kernel generator, CabIR runtime and packaging.

## Current baseline

- NAM 0.25: exact interleaved history, register-accumulated taps, fast I/O,
  three-band EQ and gate. Eco currently runs six network samples per eight
  pedal samples. Full rate is a separate template.
- CabIR 0.30: one cabinet per effect, 32 FIR taps + six fitted biquads, two
  optional tone filters; 16 capture slots. Historical 256-tap/HIR3A advice is
  superseded by the working local cabinet engine.
- Prior hardware successes/failures are recorded in NAM-RUNTIME-INVESTIGATION.
  Register groups of eight, straight-line taps, activation fusion and the
  previous combined NAM/cab experiment already failed performance or size
  checks. Do not repeat those unchanged.

## Reproduced measurement

Ran installed local Ziddle `namcheck` against `dist/NAM2smok.ZDL` (Eco 6/8)
and `~/ziddle/inputs/plucks_hiss.f32`, Input/Output/Mix 44/27/100, Gate 0.
Logs/audio: `build/probes/dsp-audit-2026-10-06/`.

| EQ | Min | Median | Max |
|---|---:|---:|---:|
| 50 / 50 / 50 | 13070 | 13654 | 15314 |
| 52 / 50 / 50 | 13218 | 13802 | 15462 |

Moving Bass just off flat adds 148 cycles (~1.08% median) in this fixture.
These are instruction-emulator measurements, not physical CPU percentages;
they exclude hardware cache stalls, firmware scheduling and live edit work.
They measure NAM alone, not the full chain. Maxima matter as well as averages.
The loader regression suites passed 14/14 tests.

## Findings and holes

1. **EQ cost is all-or-nothing.** `namlite.c` skips all three filters only when
   every selected coefficient row is flat. Any active band runs all three.
   With the half table, 49 maps to flat 50; use 52 for unambiguous tests.
   Earlier separate per-band loops were slower: avoid treating those as an
   automatic optimization. Local-state or specialized single-band paths need
   target-code measurement and a size check.
2. **Edit crackles and persistent overload need separate tests.** Ask whether
   crackling stops when rotation stops. Repeat on the pedal disconnected from
   PE, with only NAM+CabIR present. A bypassed extra effect is not equivalent
   to removing it. Compare a small EQ cut as well as boost, and repeat with
   lower NAM Output to separate signal clipping from timing pressure.
3. **EQ changes are unsmoothed.** Tone rows change at callback boundaries with
   old recursive state retained; returning fully flat clears state abruptly.
   Both are possible transition-click sources, not proof of sustained
   overload. Adding smoothing alone costs more and cannot cure missed
   deadlines. Coefficient interpolation must also be checked for stability.
4. **Gate 0 still computes the detector.** Sum-of-squares, envelope and gain
   logic run even with Gate disabled. A once-per-callback bypass after gain
   settles is worth measuring; preserve re-enable behavior. Skipping the NAM
   network whenever the gate closes would invalidate its history on reopen.
5. **Eco grouping is inherited from full rate.** `_regacc_block(group=4)`
   splits six samples into 4+2. Compare 3+3 and 2+2+2 using the same weights,
   rate and accumulation order. Gains are unknown; more loop overhead can
   outweigh lower register pressure. This is the most focused unexplored
   scheduling candidate found in this pass.
6. **Eco is a tonal trade-off.** Input pairs are selected on a nonuniform grid
   for 6/8, followed by linear reconstruction; 48 kHz models also run without
   proper rate conversion. The reported through-cab band match on Smokey is
   not universal capture equivalence or an aliasing measurement. Do not lower
   the rate further as a supposedly transparent optimization.
7. **Eco warm-up counts output frames.** 8192 pedal samples execute only
   6144 network steps at 6/8, less than the documented 6347-sample receptive
   field. History is initialized, so this is a settling/transition concern,
   not an uninitialized-memory claim or a sustained-load explanation.
8. **DSP admission costs are estimates.** Current packaging sets full/Eco/cab
   to 205/185/10. These can discourage oversized chains but do not reserve
   execution time or guarantee clean audio. The loader guide's wording
   “real share” and promise of DSP Full instead of crackling overstate the
   evidence. Raising metadata cannot make the existing chain faster.
9. **CabIR has limited remaining payoff.** Latest notes give 784/818 cycles,
   versus ~14k for Eco NAM. Cutting cabinet cost 25% would save only ~200
   cycles. Mix=0 still runs its filters; a dry-path optimization is possible
   but does not help the normal fully-wet NAM+cab use case.

## External comparison

The requested repository is private but accessible through the user's GitHub
connection. Inspected revision `0ff67608df50476ddfa748e5c4eb424e62c4ae8e`:
https://github.com/Leemuzhko/ZOOM_development

Relevant references (no external code incorporated):

- `NAM/sdk/docs/NAM_V23_CRACKLE_TESTS_RU.md`: parameter-edit isolation tests.
- `NAM/sdk/docs/NAM_V24_EDIT_DRY_RU.md`: diagnostic control and active
  optimization inventory; hardware result still pending in this document.
- `NAM/sdk/docs/NAM_MS70CDR_OPTIMIZATION_EXPERIMENT_RU.md`: padded pair
  histories, compact weights, fixed kernel-length loops; historical status
  must be read alongside later notes.
- `NAM/sdk/docs/DSP_COST_230_HYPOTHESIS_RU.md`: admission metadata versus
  actual execution time.

Their reported edit-only symptoms make an invariant-audio edit control useful
here. Their current pair engine is not a proven faster replacement for ours;
compiler initiation intervals cannot be compared as full callback timings.
They explicitly compile with interrupt_threshold=1; our inspected builder
does not set it and TI listings contain DINT/RINT sections. Compare interrupt
policy in isolation if edit-only crackles are confirmed; changing it can alter
scheduling and performance, so this is a hypothesis, not an established fix.

## Recommended order

1. Pin exact exported/installed hashes and establish stationary versus moving
   EQ symptom, plus low-output/cut controls.
2. Screen 6/8 groups 3+3 and 2+2+2; preserve rate/model/math and compare actual
   TI output, median/p99/max cycles, state guards and load size.
3. Screen local-state EQ and gate-off shortcut independently; reject regressions
   at flat EQ, active EQ, wrap positions and transitions.
4. If edit-only, compare firmware-edit control and interrupt policy before
   changing tone or resampling. Do not remove the mandatory host handshake.
5. Hardware A/B the best single candidate alone, then NAM+CabIR with EQ active.
   Leave the currently working dist/templates intact until then.
