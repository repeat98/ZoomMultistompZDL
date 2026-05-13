# Contributing

## What this repo most needs (in priority order)

1. **ToTape9 load-safety results.** The current full-kernel `ToTape9.ZDL`
   crashes on load on the test MS-70CDR. The most useful reports now are
   tightly split variants: same 9-parameter UI with `audio_nop: true`, same UI
   with pass-through DSP, reduced 2- or 3-parameter shells, and no-divide DSP
   builds.

2. **Hardware results for page 2/3 parameter handlers.** The linker can now
   synthesize LineSel-cloned edit handlers for knobs 3..9, but the current
   ToTape9 failure means this area still needs isolated confirmation. Report
   whether 4+ knob builds load, render, and update `params[7..13]`.

3. **A cleaner reloc-free knob 4-9 edit handler.** Every stock 9-knob effect
   (LO-FI Dly, etc.) has handlers tightly coupled to lookup tables that do not
   exist in our plugins. A compact hand-written or proven stock-derived handler
   would reduce the load-shape risk.

4. **Preset/bypass/state lifecycle reports.** `ctx[3]` is proven enough for
   `StereoChorus`, but we still need precise reports about whether bypass,
   preset switching, duplicate instances, and reloads preserve or clear state
   like stock effects.

5. **Block size empirical confirmation.** The audio loop processes
   "8 samples per channel × 2 channels" per call (`MVK 2,B0` outer
   loop in stock effects), but the call frequency is inferred. A
   plugin that emits a known-period tone from a sample counter would
   pin this down.

## Workflow rules of thumb

* **Read the safe-DSP rules first.** New ports should follow
  [SAFE-DSP-RULES.md](SAFE-DSP-RULES.md): start load-safe, avoid large state,
  and add DSP complexity only after a hardware smoke test.
* **One small experiment per build.** Real hardware is the only
  source of truth for anything not directly observed in stock ELFs.
  Don't pile multiple unverified changes into one flash.
* **Audio-NOP smoke test first.** Set `audio_nop: true` in the
  manifest to swap the DSP for a `B B3` stub. If that boots and the
  UI works, the linker output is structurally correct and any
  remaining issues are in the DSP.
* **Diff against stock.** Before believing a load-bearing constant
  is right, find one stock ZDL that uses it. The
  [working_zdls/](../working_zdls/) directory has all 128 factory
  effects.
* **Don't touch `Dll_<Name>`.** It's a verbatim 200-byte copy of
  NoiseGate's entry function with 4 reloc points repatched. Earlier
  attempts at a smaller `Dll` body caused inconsistent freezes. The
  bytes stay.

## Style

* Match the surrounding code. The linker uses snake_case throughout.
* Comments earn their place by explaining *why* — particularly the
  experiment that justified a magic constant. Don't write comments
  that describe what the next line literally does.
* When you add a `[v1-empirical]` or `[ASSUMPTION]` marker, also link
  back to the experiment (file + line, or a one-paragraph note in
  ABI.md) so future readers can audit the claim.
