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
* Use release ZDL filenames with unique basenames of 8 characters or less.
  Zoom tooling/device code can truncate longer basenames, and duplicate
  post-trim names have been reported to freeze the pedal when loading.
  **Confirmed on hardware 2026-09-29:** `NAMLite-amptrec.ZDL` + `NAMLite-smokey.ZDL`
  (both `NAMLite-`) froze the pedal on boot; each alone was fine.
  `build/extract_effect_db.py` now refuses to run over such a dist/.
* **Declare an honest DSP cost** (`LinkerConfig.dsp_cost`, descriptor self-entry
  +0x28). The firmware sums it per patch and shows "DSP Full" above ~230
  (community measurement, MS-70CDR 2.10: github.com/Leemuzhko/ZOOM_development,
  NAM/sdk/docs/DSP_COST_230_HYPOTHESIS_RU.md). Stock effects declare 11.6-127.7
  (median 25; Great Muff 30.43). The linker default 20.0 is a placeholder: a
  heavy effect declaring 20 lets the pedal build a chain that overloads and
  crackles instead of refusing it. NAM declares 194 (full) / 188 (Eco 7/8) /
  177 (Eco 6/8), CabIR 10. THIS pedal's limit, measured with pass-through
  probes declaring a fixed cost next to Great Muff (30.43): 224.4 accepted,
  228.4 refused -- below the ~230 reported elsewhere. PE's meter uses 228. The same research also confirmed our size cap (~30 KB
  code+data, layout-dependent) and a 9-control maximum.
* **Size cap: keep a ZDL at or under 32,126 bytes (code+data 29,576).**
  Confirmed on hardware 2026-09-30/10-02: everything up to those sizes loaded;
  NAM 0.24 (32,998 / 30,336) froze the pedal on load, and so did TSize2 -- the
  working NAM 0.23 padded with dead data to 33,174 / 30,512 -- so it is size,
  not code. The real cap lies in between (a 32 KB = 32,768-byte file limit
  fits). `build/zdl_size_guard.py` enforces the proven sizes; the dist/ DB
  build, the NAM template packager and the trial builder all call it.
* **Never use a `switch` (or a dense `if/else` on an int) in `.audio` code.**
  The compiler lowers it to a jump table: a `.switch:<func>` section of
  absolute code addresses reached by an INDIRECT branch (`B An`/`B Bn`). Those
  addresses need relocation, but ZDLs link with **zero relocations**, so the
  branch lands on garbage and the DSP freezes. Replace with straight-line
  arithmetic (e.g. `2^n` via `(float)(1<<n)`; `2^-n` by building the IEEE-754
  exponent field `((uint32_t)(127-n))<<23` — no divide, no table). Verify with
  `dis6x`: there must be no `.switch:*` section and no register-indirect branch
  other than `B B3` (the return). This freeze is insidious because if the
  switch result is unused the compiler deletes it (so a pass-through smoke build
  looks fine) — it only appears once the result is actually consumed.
* **The general rule behind that one: never materialize a code address as an
  absolute constant.** A jump table is just the compiler doing it for you. The
  same freeze is available by hand — `MVKL/MVKH` a link-time address into a
  register and `B` through it is byte-for-byte the same defect, and the
  hand-written `_init` in `build/init_materialize.asm` shipped exactly that for
  four hardware attempts. `TEXT_VA` is `0x00000000` in the linker, so an
  "absolute" target is really a section offset that is correct **only** while
  text loads at zero. Use a PC-relative `B` to a symbol so call and return both
  follow the load base.

  This inverts the usual reading of the zero-relocation rule. `Applied 0 .obj
  relocations` is normally the success line; here the *missing* relocation was
  the bug. When you emit a branch target yourself, "there is no relocation for
  it" means "this only works at link base", not "this is clean". Check
  `.rela.dyn` for your own emitted calls, and test at a nonzero text base —
  the emulator loads at zero, so it cannot see this class at all.

## Known Freeze Patterns

* Large Airwindows delay/reverb/chorus state arrays in `.fardata`.
* Small statics compiled into `.bss` or B14/SBR-relative addressing.
* `switch` statements / jump tables in `.audio` (indirect branch through an
  unrelocated `.switch` section). This froze Mangle across ~6 rebuilds — a
  `mg_crush_scale(bits)` switch was called every buffer and its jump table's
  indirect branch landed on garbage. The freeze presented as "turning the knob
  freezes the pedal" because the knob changed the switch index. Every red
  herring (granular reads, feedback, denormals) was ruled out only after
  disassembly showed the `.switch:Fx_DLY_Mangle` section + `BNOP.S2X A5`.
* Hand-written absolute call targets — the same defect without a compiler.
  `build/init_materialize.asm` loaded a link-time handler address with
  `MVKL/MVKH` and branched through it, with no `.rela.dyn` entry. Four
  hardware attempts froze on boot. A zero-call variant of the same frame booted
  fine, which is what eventually localised it: no calls, no absolute targets.
  Fixed by branching PC-relative to the handler. See
  [PARAM-INIT-INVESTIGATION.md](PARAM-INIT-INVESTIGATION.md).
* New external `__c6xabi_*` helpers beyond the tiny set already handled by
  the linker.
* Helper-heavy DSP paths in the first executable build. `ToTape9` cleared
  ctx[3] lazy init but froze in the old derived-parameter/`computeHDB` path
  before the 8-sample loop; the no-divide full build is the version that
  hardware-reported as running.
* Object-defined C/asm `ZOOM_EDIT_HANDLER` symbols for multi-page UIs.
  `T9NoAudio` loads with the DSP NOPed, then freezes on knob/page interaction.
* Calling stock-cloned edit handlers from custom `_init`. `InitProbe` proved
  the setup callback alone can load, but setup plus one cloned LineSel edit
  handler froze on boot.
* Stock edit-handler blobs whose internal references were not cloned or
  patched for this plugin.
* Category/SONAME mismatch, for example `gid=3` with `ZDL_MOD_...` or
  `gid=6` with `ZDL_DRV_...`.
* Duplicate effect filenames after 8-character basename truncation. For
  example, `TapeEcho4.ZDL` can become `TapeEcho.ZDL` and collide with a stock
  or custom `TapeEcho` install.

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
7. Avoid the object-defined edit-handler macro for release ports until a compact
   reloc-free page 2/3 handler is proven. Prefer isolated handler probes before
   coupling a multi-page UI to a full DSP kernel.
8. Do not publish an Airwindows effect as a port until the source DSP is the
   DSP being run.
