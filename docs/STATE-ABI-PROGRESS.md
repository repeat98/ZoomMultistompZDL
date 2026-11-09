> Investigation correction (2026-09-10): the local template disassembly sets
> state[21] to **0xc00ca380**, not 0xc00c8c80 as historical entries below say.
> The init dispatch is now identified at 0xc00c3c74, with B14[98] set to 1.
> See [PARAM-INIT-INVESTIGATION.md](PARAM-INIT-INVESTIGATION.md) for the trace.

# State ABI Progress

Last updated: 2026-05-19 (per-slot table region reinterpreted as RAM)

This is the compact current-state map for the hardware probes. The older
probe-by-probe chronology is preserved in git history through commit
`dc5eedb`; keep this file focused on durable findings and next decisions.

## Current Conclusions

* Large Airwindows state must not live in `.fardata`. Stock ZDLs usually keep
  `.fardata` tiny, and large custom writable static data has frozen hardware.
* `ctx[3]` is the large host-managed descriptor arena. It is readable, writable,
  persistent across audio callbacks, and per instance in the tested duplicate-FX
  cases.
* The default `ctx[3]` allocation is large enough for `StereoChorus`: hardware
  probes reached at least 705,536 bytes. The exact upper byte is no longer
  needed for the current ports.
* `StereoChorus` is the best state reference: it uses `ctx[3]`, lazy clears its
  large buffers, and the current release was reported to sound like Airwindows
  `StereoChorus`.
* ToTape9's load crash was not a ctx[3] lazy-init failure. `T9InitOnly`
  clears/finalizes the default state and loads cleanly. Removing runtime
  `__c6xabi_divf` from the full DSP path produced a hardware-reported working
  `dist/ToTape9.ZDL`. The reload mute bug was addressed in the next build by
  treating zero user slots as unmaterialized defaults and by scaling the
  LineSel raw `0..0.14` handler range before caching critical controls.
* The C/asm `ZOOM_EDIT_HANDLER` macro is not a safe release path for multi-page
  controls. `T9NoAudio` loads with DSP NOPed, then freezes on knob/page
  interaction.
* Stock-style init setup is partly mapped. `InitProbe` stage 2 proved a
  custom `_init` can safely call the host's coefficient-table setup callback
  through `__c6xabi_call_stub`, once PCR_S21 external relocations are patched
  correctly. Stage 3, calling a cloned LineSel edit handler from that init
  context, froze on boot. The likely missing ABI detail is the init-time host
  state/callback table expected by stock edit handlers.
* Static LineSel RE now identifies the first important fields in that
  init/edit state object. Stock LineSel init uses `state + 136` as a setup
  callback pointer, passes `state[1]`, `_Fx_FLT_LineSel_Coe`, and the
  coefficient-table byte size, then calls the edit handlers. Those edit
  handlers also dereference `state[31]`, `state[21]`, and tail-call
  `state[7]`.
* Firmware handler dispatch now gives the exact state base used for stock
  init/edit calls. The SonicStomp handler invoker at `c00bb460` looks up a
  descriptor entry, loads entry word 7 (`+0x1C`, the handler pointer), calls
  `c00c8e6c(slot)`, and branches to the handler with that result in `A4`.
  `c00c8e6c(slot)` returns `0x11f03000 + slot * 0xD4`, so stock init/edit
  handlers receive a 212-byte per-slot runtime state object. The earlier
  164-byte block near `c00a5406` is loader-adjacent scratch, not the main
  handler state object.
* Firmware state-template init now maps the first critical callback fields.
  `c00c8ac0..c00c8e64` writes a 53-word template into each of the six
  per-slot handler states, advancing by `0xD4`. Initial template values include
  `state[7] = c00cc94c`, `state[21] = c00c8c80`, `state[31] = c00b820c`,
  `state[34] = c00ddda0`, and `state[35] = c00dbae0`.
* Category visibility is partly host/browser state. On the MS-70CDR test
  pedal, Drive-category `ToTape9` could flash but stayed hidden until at least
  one stock Drive effect was also installed.
* A hand-decoded ZD2 `Fx_SFX_LineSel` audio function matches the ZDL LineSel
  signal-flow semantics even though the context layout and code placement
  differ. It reinforces that LineSel uses a coefficient table (`K0`, `K4`,
  `K5`, `K6`) plus effect input/output, pedal output accumulator, and a
  per-sample current-sample store.

## Runtime Map

The minimal custom audio entry map is:

| Field | Status | Meaning |
|---:|---|---|
| `ctx[1]` | confirmed | parameter float table |
| `ctx[2]` | partial | stock state/scratch header; small derived blocks at `+0x10` and `+0x18` are writable and persistent |
| `ctx[3]` | confirmed | large descriptor: `[0] = base`, `[1] = end`, `[2] = span/length` |
| `ctx[4]` | confirmed | dry/input buffer |
| `ctx[5]` | confirmed | effect/wet buffer |
| `ctx[6]` | confirmed | output accumulator; add into this, do not overwrite |
| `ctx[11]` | confirmed-use, partial-purpose | current-sample/magic-shuttle destination chain |
| `ctx[12]` | confirmed-use, partial-purpose | current-sample/magic-shuttle source buffer |
| `ctx[13]` | stock-used, partial | auxiliary buffer pointer; read-only in `AIR` (2x), `BENDCHO`, `FLANGER`, `PHASER`, read+write in `PLATE` (accumulator-style) and `TAPEECH3`. **Not used at all by mono-shape effects** (CHORUS, STCHO, DELAY, HALL, ROOM, LineSel, TREMOLO, AUTOPAN). Pattern fits "additional bus/aux pointer for stereo cross-feed or modulation reverb networks" rather than "right-channel of main wet bus" (which would have forced STCHO to use it). |
| `ctx[14]` | stock-used, partial | counterpart to `ctx[13]`; same access pattern across the same effects. PLATE writes both ctx[13]/ctx[14] in the same statement region — likely an L/R pair of one aux/accumulator bus. |

Audio buffers are float32. The observed stock/custom-safe pattern processes
8 samples per channel per callback: `LLLLLLLL RRRRRRRR`.

## Hardware-Proven Milestones

| Probe / build | Finding |
|---|---|
| `ParamTap` / LineSel handlers | First two stock-derived knob handlers update `params[5]` and `params[6]`. |
| `StatePing` | `ctx[2] + 0x10` and `ctx[2] + 0x18` can be written without crashing. |
| `StateIso` | `ctx[2] + 0x18` behaves per instance in the tested two-slot case. |
| `StateComb` | `ctx[2] + 0x18` can hold small DSP history, not only stamps. |
| `DescComb` | `ctx[3]` descriptor memory can hold audible delay history. |
| `DescSize` | Default `ctx[3]` descriptor allocation is at least 705,536 bytes. |
| `DescIso` | Duplicate instances do not share observed `ctx[3]` descriptor memory. |
| `StChorus` | Large stateful Airwindows-style effect can run from `ctx[3]`. |
| `T9InitOnly` | ToTape9-sized lazy state init/clear is load-safe. |
| `T9NoState` | A simple ToTape9-shaped DSP path can run; Input audibly changes gain. |
| `ToTape9` | No-divide full DSP loads and runs on the test MS-70CDR. |
| `VerbTiny` | First Airwindows reverb candidate; builds with ctx[3] state, no `.fardata`, and no object relocations. Hardware result pending. |
| `Galactic` | Larger Airwindows reverb candidate; builds with about 528 KB of ctx[3] state, no `.fardata`, and no object relocations. Hardware result pending. |
| `TEcho4` / `TapeEcho4` | Custom Airwindows-inspired tape echo; builds with about 512 KB of ctx[3] delay state, no `.fardata`, no `.text`, and no object relocations. Tempo control is BPM+division with stock tempo descriptor flags; true host tap-tempo behavior is pending. |
| `OTT` | Custom Dynamics-category OTT-style compressor; builds with small ctx[3] state, no `.fardata`, no `.text`, and no object relocations. Hardware result pending. |
| `InitProbe` | Object-defined init setup call loads; init-time cloned edit-handler call freezes on boot. |
| `SyncProbe` | One-byte patch of `linesel_handlers.bin` (`state[31]→state[24]`) plus a `pedal_flags=0x28, max=15` descriptor entry; loads, unbypass passes audio, knob interaction does not freeze, tap tempo (left-knob click) does not freeze. Returned value is static under tap tempo with `B4=2`, so `state[24]` is reachable but the call protocol is still wrong. Confirms the descriptor + handler shape for Pattern B sync slots is load-safe on custom ZDLs. |
| `SyncPrV2` | Same `state[31]→state[24]` patch plus a second patch at handler `+0x80..+0xab` that REPLACES the SHL/state[7] tail-call with a direct `STW.D1T1 A4,*+A0[5]` (bypassing the UI postbox at `0x11f03b00`). Loads cleanly, unbypass is OK, but the pedal **freezes on knob interaction**. This proves the state[7] tail-call (and its postbox spin at `c00cc8c8`) is mandatory for user-interaction handlers — not just denormal sanitization. The dispatcher or UI thread blocks on the postbox signal that v2 never sends. So a working sync handler must invoke state[7] with a value in the range it expects (~0..255 raw → post-SHL `< 0.14` float), not bypass it. |

## Init And Edit-Handler ABI Status

Known safe enough:

* NOP init.
* Stock-style coefficient-table setup from a custom `_init`: load callback
  pointer from state offset `+136`, pass `ctx[1]`/param table, pass
  `_<AudioFunc>_Coe`, and call `__c6xabi_call_stub`.
* Stock LineSel `onf`, knob 1, and knob 2 handlers when invoked by normal user
  interaction.
* AIR's third-knob blob in limited contexts, though it is not a general
  page-2/3 solution.
* Synthesized LineSel-cloned handlers as a linker strategy, but only after an
  isolated tiny-DSP hardware confirmation.

Known unsafe:

* Calling a cloned LineSel edit handler from custom `_init`; `InitProbe` stage
  3 froze on boot after setup plus one edit-handler call.
* The object-defined `ZOOM_EDIT_HANDLER` macro path for multi-page UI builds.
  It pulls in `__c6xabi_call_stub` and freezes on interaction in `T9NoAudio`.

Current LineSel init/edit state map:

| Field | Observed use | Confidence |
|---:|---|---|
| `state[0]` | initial template value `0`; passed as `A4` to the first stock on/off/edit callback, so it is probably patched later or phase-dependent | partial |
| `state[1]` | per-slot table value loaded from `c00ee8e8 + 4*slot`; stock init/setup and handlers consume it as a likely parameter/materialization base. Table backing RAM is not in `Main.bin`; populated at runtime by code we have not yet located. | partial |
| `state[2]` | per-slot table value loaded from `c00ee900 + 4*slot`; same RAM-table caveat as `state[1]`. | unknown |
| `state[3]` | per-slot pointer `c00ee430 + 12*slot` (no load — `state[3]` is the address itself, so it is a 12-byte per-slot RAM scratch reachable through this pointer) | partial |
| `state[7]` | tail-call target after stock handler callback setup; template value `c00cc94c` | partial |
| `state[21]` | second callback pointer used by knob edit handlers; template value `c00c8c80` | partial |
| `state[24]` | template value `c00d4b40`. **Reinterpretation (2026-05-29):** reading `c00d4b40` directly shows this is a **float-math utility**, not a BPM-to-samples helper. The body starts with `ABSSP A4,A7; ABSSP B4,B7; CMPEQSP A4,0,A1; CMPEQSP B4,0,B1; OR B1,A1,B2; [B2] B B3` — early returns when either arg is float 0.0 — then runs `RCPSP`/`MPYSP` polynomial math with constants `0x3FC90000` (~π/2) and `0x3F860000`. Looks like ATAN2 or reciprocal-based division. SyncProbe v1/v1.5/v2 silent results are fully explained: A4 = state[0] = float 0.0 triggered the early-exit on every call, so state[7] received zero. The actual BPM mechanism is **somewhere else** — TAPEECH3's `DLY_EP3_Calc_DelayTime` uses state[24] as one of several math helpers but the BPM input comes from state[31] (with `B4=4`) earlier in the chain. See [TEMPO-SYNC.md](TEMPO-SYNC.md). | partial |
| `state[30]` | sync-division / mode query; returns `4` for "free time", else a division index. Template value `0xc00c3a70`. See [TEMPO-SYNC.md](TEMPO-SYNC.md). | partial |
| `state[29]` | per-slot pointer `c00ee9f0 + 4*slot` (no load — 4-byte per-slot RAM scratch reachable through this pointer) | partial |
| `state[31]` | **per-slot table lookup** (not a dispatcher). Template value `c00b820c`. Body is 5 instructions: returns `*(0xc009c1a0 + 44*slot + 4*B4)`. So `B4` is a column index into a 44-byte/11-entry per-slot row. `B4=2`/`B4=3` return raw 0..255 knob values; `B4=0` is a pointer (null-checked at `c00d2110`); `B4=9` feeds into the state[34] coefficient setup. Other columns unmapped. **BPM is not in this table** (per-slot, but BPM is global). See [TEMPO-SYNC.md §3](TEMPO-SYNC.md). | partial |
| `state[34]` / `state + 136` | setup callback pointer for coefficient-table registration; template value `c00ddda0` | hardware-safe in `InitProbe` stage 2 |
| `state[35]` / `state + 140` | second setup callback used by many multi-param stock init functions; template value `c00dbae0` | partial |

Stock-sample scan:

`build/analyze_stock_init_handlers.py` now checks this pattern mechanically
against stock disassembly. A sample across LineSel, Exciter, OptComp, ZNR,
BottomB, Air, Delay, StereoCho, TapeEcho, Hall, AutoPan, and Phaser found:

| Pattern | Sample result |
|---|---|
| Init setup callbacks | `state + 136` appears everywhere checked; most multi-param effects also use `state + 140`. |
| Init edit calls | Stock init calls the effect's own edit handlers after setup. |
| Edit callback fields | `state[31]` is common; output/value handlers often also use `state[21]`; on/off and some time/rate handlers use `state[7]`. |

This turns the ToTape9 first-touch/reload parameter bug into a general ABI
gap: we can run DSP safely, and we can let stock handlers run from normal UI
interaction, but we do not yet know how to recreate the full stock init-time
edit-handler callback environment for custom init.

Firmware-side scan:

`build/find_firmware_state_offsets.py` now scans `main_os.dis` for the same
suspected fields. It found that the loader-adjacent 164-byte block initializes
`+128/+136/+140/+148/+152` to `-1`, `+132/+144/+156` to `0`, and word 31 to
`1` before the ELF magic check. Later firmware regions write/read `+140` and
`+136` as table indices/sentinels rather than obvious function pointers.

That means the stock init state is probably phase-specific or late-bound. The
custom `InitProbe` stage 3 failure should not be fixed by simply copying the
`c00a5406` allocation layout; the exact handler state base is now known, but
we still need to map who writes its callback fields before embedded ZDL
`_init` is entered.

Handler-dispatch anchor:

The exact handler state pointer is now mapped. `get_entry` at `c00b056c`
returns a SonicStomp entry pointer for `(slot, entry_index)`, using the
48-byte entry stride. The generic handler path at `c00bb460` does:

1. `get_entry(slot, entry_index)`.
2. Load `entry[7]`, the on-disk SonicStomp `func_ptr` field at offset `+0x1C`.
3. Call `c00c8e6c(slot)`.
4. Branch to the loaded handler pointer with `A4` still holding the
   `c00c8e6c` return value.

`c00c8e6c(slot)` is simple:

```
return 0x11f03000 + slot * 0xD4;
```

So stock on/off, init, and edit handlers receive a 212-byte per-slot runtime
state object. Entry index `1` is the effect-name entry and therefore the
stock init function; user parameters are the later descriptor entries. This
is the best current anchor for the parameter-materialization bug.

Per-slot state template:

`c00c8ac0..c00c8e64` initializes the handler state block before stock handlers
run. It starts with `A4 = 0x11f03000`, `A15 = 0xD4`, and `B0 = 6`, writes a
53-word template, then advances `A4 += 0xD4` until all six slots are covered.

The template gives concrete initial values for the callback fields already
seen in stock LineSel/Exciter disassembly:

| Field | Byte offset | Initial template value | Current read |
|---:|---:|---|---|
| `state[7]` | `+0x1c` | `c00cc94c` | stock edit handlers tail through this path |
| `state[21]` | `+0x54` | `c00c8c80` | second callback in many knob/value handlers |
| `state[31]` | `+0x7c` | `c00b820c` | first callback in on/off and knob handlers |
| `state[34]` | `+0x88` | `c00ddda0` | coefficient-table setup callback at `state + 136` |
| `state[35]` | `+0x8c` | `c00dbae0` | second setup callback at `state + 140` |

The same loop also shows the non-callback slot sources:

| Field | Template source | Current read |
|---:|---|---|
| `state[0]` | literal `0` | source for the first callback's `A4`; likely patched later or phase-dependent |
| `state[1]` | `*(c00ee8e8 + 4*slot)` (LDW) | likely setup/materialization base |
| `state[2]` | `*(c00ee900 + 4*slot)` (LDW) | unresolved per-slot value |
| `state[3]` | pointer `c00ee430 + 12*slot` (no load) | 12-byte per-slot RAM scratch, addressable via this pointer |
| `state[29]` | pointer `c00ee9f0 + 4*slot` (no load) | 4-byte per-slot RAM scratch slot |

The full TIPA scan of `firmware/Main.bin` confirms the gap `c00ed164..c00eebb4`
is not present in any YSX chunk. All 11 YSX sections were parsed (header is
`'YSX'` + 4 LE load-addr + 4 LE size, 11 bytes total) and they cover
`c009dfb0..c00ed164` then resume at `c00eebb4..c00f1364`, plus the
`11817000..1181dd60` RAM-side data sections. So the c00ee* tables are not
"unextracted static data"; they are uninitialized firmware RAM that some
runtime code populates after boot.

Distinction made explicit by re-reading the template-writer disassembly:

* `state[1]` and `state[2]` are loaded with `LDW` from `c00ee8e8 + 4*slot` and
  `c00ee900 + 4*slot`. Those are the only true table reads. Whatever non-zero
  values live there must be written by some other firmware path.
* `state[3]` is `B5` itself, which is the address `c00ee430 + 12*slot`. There is
  no load. `state[3]` is therefore a per-slot pointer into RAM. The 12-byte
  stride matches the slot count (6), so the table is 72 bytes of per-slot RAM
  scratch reachable through `state[3]`.
* `state[29]` is `B3` itself, which is the address `c00ee9f0 + 4*slot`. Same
  pattern — a 4-byte per-slot RAM cell reachable through `state[29]` (24 bytes
  total for six slots).

No stores into `c00ee430/c00ee8e8/c00ee900/c00ee9f0` were found in
`main_os.dis`, `chunk2.dis`, or in the wrapped disassemblies of
`chunk_c00ef*.out` and the `chunk_1181*.out` RAM-side chunks. The c00ee8e8 and
c00ee900 reader at `c00d2080+` consumes the loaded value and feeds it into
`CALLP 0xc00cc94c` (the `state[7]` template callback), confirming the table
acts as a per-slot handle that flows into stock state[7] dispatch.

Open RE leads:

* Indirect writers (`STW B5, *Ax` where `Ax` was previously set to a c00ee*
  address) are not yet covered by the current pattern scan; a register-tracking
  scan that follows MVK/MVKH pairs across MV.L moves would catch them.
* Effect-activation/preset-load code (not yet identified) is the most likely
  populator of `c00ee8e8`/`c00ee900` since those values are consumed by stock
  state[7] dispatch.
* `state[3]` and `state[29]` being writable RAM pointers means stock handlers
  may use them as private per-slot scratch; checking stock edit handlers for
  loads/stores through `state[3]`/`state[29]` is the cheap next step.

This makes `InitProbe` stage 3 more interesting: the cloned edit handler should
have had the same template callback addresses available by the time stock-style
init ran. The remaining missing detail may be a phase flag, argument register,
or per-effect field (`state[0]`, `state[1]`, descriptor-derived values) rather
than simply absent callback pointers.

Dispatch-side lead:

Firmware has a tiny generic function-pointer wrapper at `c00d3bec`, and
loader/runtime regions at `c00a4db0..c00a4e38` and `c00a6ab0..c00a6b64` call
through it while walking fields that look like callback lists:

| Field | Observed use in those regions |
|---:|---|
| `word20` | optional direct callback pointer |
| `word21` | base/list pointer used during callback iteration |
| `word22` | byte/count-like value that gates the `word21` iteration |

This is not yet tied to embedded ZDL `_init`. The next check was to identify
the record family feeding these lists; that check reclassified the parser as
ELF dynamic-table handling rather than normal parameter materialization.

ELF dynamic-table correction:

The loader parser at `c00a61b8..c00a62e0` walks packed 8-byte records from a
table rooted at its `state[19]`, but the explicit type values now match ELF
dynamic tags rather than SonicStomp/UI descriptors:

| Type | ELF meaning |
|---:|---|
| `12` | `DT_INIT` |
| `13` | `DT_FINI` |
| `14` | `DT_SONAME` |
| `20` | `DT_PLTREL` |
| `22` | `DT_TEXTREL` |
| `23` | `DT_JMPREL` |
| `25..29` | init/fini arrays, sizes, and runpath |
| `32..33` | preinit array and size |

A corpus scan over 830 stock ZDL files found 825 normal `PT_DYNAMIC` tables.
None of those 825 contain `DT_INIT`, `DT_FINI`, `DT_INIT_ARRAY`,
`DT_FINI_ARRAY`, `RUNPATH`, or `PREINIT_ARRAY`. The current custom linker also
does not emit them. So the previous "type 13 may be descriptor materialization"
lead should be treated as a loader-general path for uncommon dynamic tags, not
as the normal stock init/edit parameter path. Parameter materialization should
stay focused on the SonicStomp init entry and the stock edit-handler state
callbacks (`state + 136/+140`, `state[31]`, `state[21]`, `state[7]`).

## ToTape9 Split Status

| Variant | Result | Meaning |
|---|---|---|
| `T9Meta` | loads | descriptor/image/link shape can load when DSP is NOPed. |
| `T9NoAudio` | loads, then freezes on edit/page change | object-defined edit handlers are a separate UI-interaction failure. |
| `T9NoHand` | freezes on load | full DSP path is unsafe. |
| `T9NoInit` | loads | returning before state init is safe, but DSP never enters. |
| `T9InitOnly` | loads | lazy ctx[3] init/clear/finalization is safe. |
| `T9DspNoLoop` | old build froze; current no-divide split no longer the priority | parameter derivation / `computeHDB` builds without `__c6xabi_divf`. |
| `T9NoState` | loads | helper-light scalar DSP path is viable. |
| `ToTape9` | loads and runs | full ctx[3]-backed no-divide DSP is viable enough for listening/exactness work; Drive category needs a stock Drive effect present on MS-70CDR to show in the pedal browser. |

Next ToTape9 work:

1. Verify the zero-as-unmaterialized parameter fallback. ToTape9 still treats
   the host parameter table as read-only. Nonzero values in the LineSel
   `0..0.14` raw range are normalized before use/cache; zero/NaN values fall
   back to manifest defaults because reload can expose zeroed params before an
   edit interaction materializes the host table. This means true knob-at-zero
   cannot currently be distinguished from "not materialized yet".
2. Test whether saved presets and preset switches preserve edited values with
   the read-only fallback path.
3. Add a desktop comparison harness before calling ToTape9 source-equivalent.
4. Separately build a tiny-DSP page 2/3 parameter probe using synthesized
   LineSel-cloned handlers to prove `params[7..13]` updates independently from
   the tape kernel.

## LineSel / Parameter-Materialization Clue

A hand-decoded ZD2 `Fx_SFX_LineSel` function is not ABI-identical to the ZDL
`Fx_FLT_LineSel`, but it is semantically close. The ZD2 version loads a
coefficient table from `A4`, then uses `K0`, `K4`, `K5`, and `K6` while moving
samples between effect input/output and pedal output. The ZDL MS-70CDR
LineSel disassembly shows the same coefficient roles through `ctx[1]`.

This helps explain the parameter/default bug. Stock LineSel is not relying on
raw UI fields magically being valid in the audio loop; its init/edit-handler
path materializes coefficient-table values before audio uses them. Our custom
builds borrow or synthesize LineSel edit handlers but still do not have a safe
general way to call those handlers from custom init. Therefore a fresh load or
reload can expose zero/unmaterialized user slots until the user touches a
parameter. Audio-side default fallbacks and per-parameter materialization flags
remain the safest current workaround.

The ZD2 snippet also makes `ctx[11]`/`ctx[12]` less mysterious for ZDLs: the
"magic shuttle" appears to be a current-sample store path used by LineSel-style
host callbacks, not arbitrary decoration. Preserve it exactly unless a probe
proves a narrower rule.

## Reverb Port Status

`VerbTiny` was chosen as the first reverb target because its Airwindows delay
network is much smaller than the older `Reverb`/plate families. The current
Zoom port keeps the VerbTiny delay constants, five source parameters, matrix
feedback structure, and bezier undersampling/filter reconstruction, but stores
the network in a rectangular `ctx[3]` state layout rather than source C++
member arrays. The Airwindows float dither tail is omitted like the other Zoom
ports.

`Galactic` is the next reverb candidate. It uses the original Galactic delay
network converted from double to float32 in `ctx[3]`, with about 528 KB of
delay/scalar state. The build assumes 44.1 kHz (`cycleEnd = 1`) and omits the
Airwindows dither tail.

Hardware status: both are untested. First tests should be basic load,
unbypass, page 2 parameter interaction, reload, and duplicate-instance
behavior.

## Custom Tape Echo Status

`TEcho4` / `TapeEcho4` is intentionally a custom effect rather than an exact
Airwindows port. It combines safe Airwindows-derived tape techniques:
TapeHack-style soft clipping, a compact 64-tap FIR derived from a clean UAD
Galaxy Tape Echo IR, adjustable wear filtering, measured transport modulation,
a compact mono spring fallback, and a
bounded stereo delay line in `ctx[3]`. The spring capture had identical left
and right channels and useful decay past one second, so the release replaces
the old `Spread` control with an experimental parallel mono `Spring` return.
Desktop listening found the first tank approximation unlike the Galaxy spring,
so `Spring` now defaults to zero pending a better pedal-safe model. Offline
listening selected a closer host reference: a 744 ms measured spring body plus
an eight-line FDN tail with `0.92` feedback, `0.55` damping, and a 320 ms
equal-power handoff. The desktop preview renderer reproduces that target when
`spring > 0`; the release ZDL does not yet contain its long measured body. The
echo path itself was positively validated in the same desktop workflow. The
FIR is stored in a read-only `.const:*` subsection; the linker now packs and
resolves named constant subsections. Total `ctx[3]` state is about 558 KB,
below the proven descriptor lower bound, with no `.fardata`. Hardware testing
still needs load, unbypass, page 2/3 parameter interaction, reload, and
duplicate-instance checks. The `Tempo` descriptor uses the stock tempo flag
pattern, but custom-ZDL access to the pedal's global tap tempo is still
unresolved. The release file is named `TEcho4.ZDL` because Zoom tooling/device
behavior can truncate basenames longer than 8 characters; `TapeEcho4.ZDL` can
collide with `TapeEcho.ZDL`.

A first pedal-safe spring experiment downsampled the selected long host
reference by 16 and distributed its FIR work across callbacks. Desktop A/B
listening rejected it: the decimation removed the spring character. Stock
`SPRING`, `SPRING63`, and `PARTICLE` analysis points to the replacement
strategy: full-rate algorithmic diffusion and irregular host-backed delay
lines, not a long embedded IR. The older `SPRING` effect is the readable
bridge: its `.const` data includes 16 irregular read addresses and 8 write
addresses. `SPRING63` expands that into a dense `ctx[2]` pointer graph, while
`PARTICLE` demonstrates a larger arena-based texture engine. The next spring
prototype should follow that stock architecture.

`OTT` is another custom effect, not a port. It confirms that small `ctx[3]`
state is practical for non-delay DSP history too: crossover memories, band
envelopes, and smoothed gains all live in the descriptor arena instead of
`.fardata`. Its first hardware test should focus on Dynamics-category browser
visibility, unbypass behavior, page-2 `SplitFrq`, and whether the aggressive
gain law needs taming for guitar-level inputs.

## Open Questions

* What declares or toggles stock stereo routing for custom ZDLs?
* Can stock tempo/tap-tempo descriptor flags feed meaningful host tempo values
  into custom ZDL parameters, or do custom effects need their own BPM control?
* What exactly do `ctx[13]` and `ctx[14]` represent in stock modulation effects?
* What are the lifecycle rules for ctx state during bypass, preset switch,
  reload, and duplicate instances beyond the cases already tested?
* Which runtime helpers are safe enough to bundle, and which must be avoided?
* Can a compact reloc-free page 2/3 edit handler be written or cloned safely?
* What init-time state fields make stock edit handlers safe to call during
  load, and are those fields available to custom effects?

## How To Record New Findings

Keep this file short:

* Add only durable conclusions or a small table row for a new hardware result.
* Move detailed flash instructions into `src/hardware_probes/` or the relevant
  effect directory.
* If a conclusion changes, replace the old claim instead of appending a long
  contradiction.
