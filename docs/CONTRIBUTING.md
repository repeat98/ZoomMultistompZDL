# Contributing

## What this repo most needs (in priority order)

1. **Hardware test results for 3+ knob plugins.** Flash the current
   3-knob TapeHack and report:
   * Does the third knob (`Output`) modulate audio when turned?
   * Does it freeze the unit at FX-select time?
   * Does the icon render correctly?

   The result settles [build/ABI.md](../build/ABI.md) §5.3.b — the
   single biggest open question — and unblocks pages 2 and 3 (knobs
   4–9).

2. **A reloc-free knob 4–9 edit handler.** Every stock 9-knob effect
   (LO-FI Dly, etc.) has handlers tightly coupled to lookup tables
   that don't exist in our plugins. Two paths:
   * Carve a 4th–9th handler out of *any* stock effect that happens to
     have a self-contained one (the kind of needle-in-haystack search
     where 76-byte, 0-relocation patterns from `.rela.dyn` analysis
     are the right tool).
   * Hand-write one in TI assembly that reads the host-state pointer,
     calls the host's "get knob value" callback with the right
     `knob_id`, and writes the result to `params[N]`. The LineSel
     handlers (extracted in [build/linesel_handlers.bin](../build/linesel_handlers.bin))
     are the template.

3. **A working `_init` handler.** Right now the linker uses a
   NOP_RETURN for `_init` because LineSel's init has unresolved
   coefficient-table refs. Most plugins don't need an init (they're
   stateless) but anything with persistent state across blocks
   (filters with history, reverbs, delays) does. Solving the static
   `.fardata` problem in [build/ABI.md](../build/ABI.md) §6 unblocks
   most of the Airwindows catalogue.

4. **Block size empirical confirmation.** The audio loop processes
   "8 samples per channel × 2 channels" per call (`MVK 2,B0` outer
   loop in stock effects), but the call frequency is inferred. A
   plugin that emits a known-period tone from a sample counter would
   pin this down.

## Workflow rules of thumb

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
