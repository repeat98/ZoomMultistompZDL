# Safe DSP Rules for Custom ZDLs

These rules are hardware-derived and cross-checked against the TI C6000 PDFs.
Follow them before porting a desktop plugin algorithm, especially Airwindows
effects. See [TI-PDF-NOTES.md](TI-PDF-NOTES.md) for the manual-backed details.
For Airwindows release work, also follow
[AIRWINDOWS-EXACT-PORTS.md](AIRWINDOWS-EXACT-PORTS.md): approximate DSP is an
experiment, not a port.

## First Build

1. Start every new effect with `audio_nop: true` or a tiny dry/pass-through
   DSP. Verify it appears on the pedal before adding audio code.
   For complex effects, keep the final parameter count, descriptor shape, and
   edit-handler strategy in this smoke test so load-time UI/linker problems are
   caught before the DSP is involved.
2. Add one DSP behavior at a time. If the pedal freezes on load or first
   interaction, the last DSP change is guilty until proven otherwise.
3. Keep the initial hardware-test DSP boring: no persistent state, no stack
   arrays, no math-library calls, no heap, no large tables.

## Hard Constraints

* Compile with `--mem_model:data=far`. The TI compiler otherwise uses
  DP/B14-relative near access for scalar globals/statics.
* Keep `.fardata` tiny and initialized. Large writable static state has frozen
  real pedals.
* Do not use `malloc`, `.bss`, `.usect`, common symbols, or uninitialised
  static storage. The custom ZDL path is not normal C runtime startup.
* Avoid `sinf`, `cosf`, `tanf`, `logf`, `powf`, and friends. The Zoom runtime
  does not provide the normal desktop math library.
* Avoid division in first hardware probes. `__c6xabi_divf` is linked by this
  repo, but no-divide DSP is easier to trust while isolating loader crashes.
* Avoid stack arrays in first hardware probes. A few scalar locals are fine;
  block-local buffers are not a safe default.
* Avoid `double`, integer division/modulo, `long long`, and implicit conversion
  code in first probes. TI may lower them to `__c6xabi_*` helper calls that
  this repo has not bundled or tested.
* Watch for `__c6xabi_push_rts` / `__c6xabi_pop_rts` from code-size
  optimization. Prefer no high `--opt_for_space` for DSP builds unless the
  helper symbols are explicitly bundled and hardware-tested.
* Treat `R_C6000_SBR_*`, `R_C6000_SBR_GOT_*`, `DSBT`, TLS, exception, and C++
  relocations as unsafe in plugin objects. They imply DP/GOT/runtime machinery
  our loader path does not provide.
* Keep function boundaries ABI-clean: return through `B3`, keep `B15` aligned,
  and do not rely on `B14` being ours.
* Always preserve the `ctx[11]` / `ctx[12]` magic shuttle pattern used by the
  existing effects.
* Treat source plugin parameter scaling and source plugin DSP as separate
  tasks. The manifest can record exact source ranges before the full DSP is
  safe to run, but that does not make the effect a real port.

## Known Freeze Patterns

* Large Airwindows delay/reverb/chorus state arrays in `.fardata`.
* Small statics compiled into `.bss` or B14/SBR-relative addressing.
* New external `__c6xabi_*` helpers beyond the tiny set already handled by
  the linker.
* Large all-at-once release shapes: 9 parameters, synthesized page 2/3 edit
  handlers, helper symbols, and a full DSP kernel in the same first hardware
  build. Current `ToTape9` crashes on load in this category.
* Stock edit-handler blobs whose internal references were not cloned or
  patched for this plugin.
* Category/SONAME mismatch, for example `gid=3` with `ZDL_MOD_...` or
  `gid=6` with `ZDL_DRV_...`.

## Practical Porting Shape

For a new Airwindows port:

1. Copy source parameter names, defaults, and formulas into `manifest.json`.
2. Generate a param header with `write_param_header(...)`.
3. Implement a no-state smoke-test DSP that uses only scalar arithmetic.
4. Build and inspect: prefer `.fardata: 0 bytes`, `Applied 0 .obj relocations`
   for the DSP object, and no unexpected external symbols.
5. Only after the pedal loads cleanly, introduce approximations of the real
   algorithm in small patches.
6. Use `ctx[3]` for full persistent delay/reverb/chorus buffers, validate its
   base/end/span fields before use, and initialize large memory lazily.
7. Do not publish an Airwindows effect as a port until the source DSP is the
   DSP being run.
