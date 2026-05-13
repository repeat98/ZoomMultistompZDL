# Airwindows Porting Context for Future Agents

The goal is not to paste desktop Airwindows code directly into a pedal build.
The goal is to make flash-safe ZDLs first, then approach the original DSP in
hardware-tested increments.

Important naming rule: if the DSP is not the Airwindows DSP, the build is an
experiment, not a port. See `docs/AIRWINDOWS-EXACT-PORTS.md`.

## Required Port Shape

Each effect directory should have:

* `manifest.json` with source parameter names/defaults/formulas.
* `build.py` that calls `write_param_header(...)` when DSP needs params.
* `<effect>.c` exporting the manifest's `audio_func_name` in `.audio`.
* A generated `*_params.h` header, ignored by git.

## DSP Safety Baseline

For first hardware tests:

* Use `.fardata: 0 bytes` whenever possible.
* Use no static delay lines, no heap, no stack arrays, no desktop math calls.
* Use no `double`, integer division/modulo, `long long`, or implicit heavy
  conversions in first probes. TI may emit RTS helpers that are not bundled.
* Prefer scalar arithmetic and fixed 16-float block assumptions.
* Keep default values dry or unity when the source plugin does that.
* Preserve `ctx[11]` / `ctx[12]` magic shuttle.
* After building, inspect linker output. A first smoke-test port should ideally
  show `.fardata: 0 bytes`, no unexpected external symbols, and no object
  relocations from DSP code.

## Compiler Rules

* Use `--mem_model:data=far`; scalar statics/globals otherwise become near
  `.bss` data accessed via `B14`.
* Avoid high `--opt_for_space` on DSP code unless you want to test the exact
  emitted helper symbols. It can introduce push/pop or call-stub RTS helpers.
* Put the audio function in `.audio` with `#pragma CODE_SECTION`.
* Generated `*_params.h` headers should be produced from the manifest so UI
  defaults and DSP fallback defaults stay in sync.

## Airwindows-Specific Trap

Many Airwindows plugins are state-heavy. `StereoChorus` has two
`int[65536]` delay buffers; reverbs and tape effects often have similar
state. Do not port those buffers into `.fardata`. For `StereoChorus`, hardware
probes have now proven enough per-instance space in `ctx[3]`; use that arena
for large state and keep `.fardata` tiny. Record the exact source parameter laws
in the manifest and document any math substitutions.

Any beta core that is not source DSP is only for ABI probing. It must not be
described as a finished Airwindows port unless it runs the source algorithm.

See `docs/SAFE-DSP-RULES.md` and `build/ABI.md` before making a port more
ambitious. See `docs/TI-PDF-NOTES.md` for the underlying TI manual notes.
