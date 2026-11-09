# Testing ZDLs against an emulated C674x

There is a working C674x emulator that runs our ZDLs headlessly: **Ziddle**
(<https://berbasoft.com/ziddle/>, CC0, Rust). It loads a `.ZDL`, runs `_init`,
runs the audio function over blocks, and lets you read the emulated memory
afterwards. That turns "does this hang the DSP" from a pedal-bricking experiment
into an error return.

**Read section 4 before you trust a result.** The emulator has told us a build
was fine four times, and the pedal froze four times.

---

## 1. Getting it

Ziddle is not vendored here — it is a separate project with its own licence and
it is large. Download the source from <https://berbasoft.com/ziddle/> and unpack
it somewhere outside this repo (the layout is a Cargo workspace with
`product/emu`, `product/formats`, `product/cpu`, … ).

Our test rig lives in [tools/emulator/](../tools/emulator/) — two Rust source
files and a `Cargo.toml`. Copy it into the workspace as `product/zdlprobe/`:

```bash
cp -r tools/emulator <ziddle>/product/zdlprobe
cd <ziddle>
cargo build --release --bin matcheck
```

Needs a Rust toolchain (`rustup`); the first build takes about a minute because
it pulls in Cranelift.

> The rig has twice been lost to a wiped scratchpad. It is in the repo now.
> Keep it there.
>
> Ziddle itself lives in `~/ziddle/ziddle-source-1787802520` (with
> `product/zdlprobe` added to the workspace members) and standard inputs in
> `~/ziddle/inputs/`. **Never in /tmp**: macOS clears it, and that has cost the
> whole setup twice. `tools/nam_prototype/host_vs_emulator.py` (TI vs host) and
> `tools/nam_prototype/make_capture.cjs` (loader-path capture builds) are in the repo.
>
> **Local fix to re-apply after a fresh download (2026-10-19).** In
> `product/cpu/src/insn/mod.rs`, `compact_unit`, the Dstk rule
> `(h & 0x8c06) == 0x8c04` must return `(Unit::D, Side::B)`: Dstk
> (`LDW/STW *B15[ucst5]`) always runs on .D2, and bit 12 only picks the data
> register file. Without the fix, a masked `STW.D2T1` to the stack under
> `SPMASK ... D2` is replayed on every SPLOOP iteration and corrupts a spilled
> value (see NAM-RUNTIME-INVESTIGATION.md, 2026-10-19).
>
> **Two more (2026-10-20), same file set:**
> - `insn/mod.rs`, `decode_compact16`, rule `(h & 0x040e) == 0x040a` (16-bit
>   SHL/SHR by a constant): the 3-bit field means 1-6 as is, **7 = 8, 0 = 16**
>   (checked against TI's dis6x on every such instruction in `dist/`). Raw,
>   `SHL 8` ran as `SHL 7`, which corrupted Loop's packed samples.
> - `state.rs`, `sploop_tick`, the SPLOOPW branch: when the exit condition is
>   false at a stage boundary, end the loop there (`exit_t = t`) instead of
>   starting one more iteration. TI-built 128-iteration loops ran 129-130
>   times and stored past their arrays (once into code).
> After both, Loop matches the host to ~1e-7 and NAM full rate is unchanged
> (2e-10). The NAM split build still differs from the host in the emulator
> (amp side near silent) while playing correctly on the pedal: a gap not yet
> found.

## 2. `matcheck` — does `_init` materialize params?

```bash
# Use the full user-knob count from the effect manifest and an explicit
# expected params[0] load value. Example for an eight-knob custom effect:
<ziddle>/target/release/matcheck --params 8 --bypass 1 dist/Gyre.ZDL
```

Checks all N normalized custom-effect user parameters and params[0] immediately
after init, then again after edit handlers. Known input values are 11,22,...;
expected user values are 0.11,0.22,... . It never calls `set_engaged` to repair the
bypass flag before observing it. The expected bypass value describes the load
state being tested; the CLI does not configure a firmware patch's on/off state.

Exit 0 requires both snapshots to match and execution checks to pass. Exit 1
means a mismatch, load/read/handler failure, missing/incomplete init, or
unsupported init instructions; exit 2 means invalid arguments. Broken shipping
initialization is expected to fail. This contract is specific to custom effects;
stock effects with nonlinear parameter laws need their own expected values.

The verdict logic can be tested without Ziddle:

```bash
rustc --test tools/emulator/src/matcheck_assertions.rs -o /tmp/matcheck-tests
/tmp/matcheck-tests
```

## 3. Useful entry points

From `ziddle_emu`:

| Call | Use |
|---|---|
| `AudioEngine::load(container, knobs, max_value, budget)` | load + run `_init` with knobs seeded |
| `eng.load_report()` | `init_present`, `init_completed`, `init_unimplemented_hits` |
| `eng.host_mut().harness.mem.read_u32(addr)` | read emulated memory |
| `host.run_edit_handlers()` / `host.edit_pass()` | call every `*_edit`, and report which failed |
| `process_zoom_block`, `set_engaged`, `set_firmware_mix` | drive audio |
| `Harness::load(bytes)` → `init_function()`, `named_symbols_sorted()` | symbols without running anything |

Constants: `BLOCK_SAMPLES=8`, `CHANNELS=2`, `PARAM_USER_BASE=5`,
`PARAMS_ADDR=0x20000100`.

## 4. What the emulator CANNOT tell you

**Correction:** the null-callback explanation below is historical and unproven.
Stock LineSel also delegates through state[7] during init. See
[the current investigation](PARAM-INIT-INVESTIGATION.md) for a firmware wait
path that is another possible explanation.

**This is the important section.** Ziddle models the C674x core faithfully. It
does *not* model the pedal's firmware, and that is where our failures live.

`ZDL_PROFILE` in `product/emu/src/runtime/profile.rs` models only these `ctx`
service slots:

```
7, 8, 21, 31, 39, 40, 45, 46, 51
```

and everything else is `Unmodeled::Zero`. Two consequences:

* **`ctx[34]` and `ctx[35]` are not modelled.** Every stock `_init` calls them
  before its handlers (`ctx[34](ctx[1], table, N)` and `ctx[35](ptr, 0, N)`).
  The emulator cannot run a stock-shaped `_init` at all, and cannot tell you what
  those calls do.
* **The modelled slots are ALWAYS present.** On the emulator `ctx[7]` and
  `ctx[31]` are valid from the first instruction. On hardware they are not
  populated when `_init` runs. Our edit handlers tail-branch into `ctx[7]` — so
  a body the emulator happily reports as `completed=true` branches into an
  unpopulated pointer on the pedal and freezes on boot.

That is exactly how four `_init` candidates passed here and bricked the pedal.
See [INIT-MATERIALIZATION.md](INIT-MATERIALIZATION.md) §11.

**Rule of thumb:** the emulator is *necessary but not sufficient*. It is
authoritative about instruction semantics — branch targets, register use, stack
discipline, whether a loop terminates. It is worthless about firmware readiness
and ordering. If a change touches anything that calls through `ctx[]`, an
emulator pass means only that you have not made an obvious mistake.

## 5. Bisecting instead of guessing

The one thing that actually moved the `_init` work forward was a probe that did
**nothing**: prologue and epilogue with zero calls between them. It booted, which
proved the frame was sound and put the fault squarely in the handler calls —
after three "candidate fixes" had each cost a freeze and a recovery.

If you are about to flash a candidate fix, consider flashing the *question*
instead. `ZDL_MATERIALIZE_INIT_MAX_CALLS` exists for this (see
[../build/README.md](../build/README.md)).

Pair it with a probe that fails safe. `MatProb` defaults its Gain knob to 0, so
"params did not materialize" is silence rather than an ambiguous noise — see
[../src/hardware_probes/README.md](../src/hardware_probes/README.md).
