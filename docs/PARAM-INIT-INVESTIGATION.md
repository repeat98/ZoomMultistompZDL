# Parameter initialization investigation — 2026-09-10

## Verified from local disassembly

Reproduced with `python3 -B build/disassemble_zdl.py
stock_zdls/MS-70CDR_LINESEL.ZDL stock_zdls/LINESEL.ZDL
--out-dir /tmp/param-init-investigation` (join onto one command line).

Stock LineSel is a counterexample to the claim that stock handlers always
compute inline and return:

- `Fx_FLT_LineSel_EfxLvl_edit`, text VA `0x60`: reads state[31] at
  `0x64`, calls state[21], loads state[7] at `0x8a`, and tail-branches at `0xa0`.
- `Fx_FLT_LineSel_init`, text VA `0xf8`: calls state[34] with
  `(state[1], 0x80000378, 28)` before calling that same handler at `0x124`
  and the second handler at `0x12c`. It preserves the context in A10.

Thus delegation through state[7] is compatible with stock initialization.
It remains unknown why the custom call path fails. P0 proves that the tested
zero-call frame boots; it does not validate every branch/callee interaction,
or identify a particular null callback. A nonzero pointer can still be invalid,
and a null check cannot establish callback readiness.

## Firmware evidence and its limits

The checked-in `firmware/extracted/main_os.dis` contains:

- `0xc00b820c..0xc00b8228`: table lookup returning the word at
  `0xc009c1a0 + 44*A4 + 4*B4`. This supports the documented state[31]
  contract as slot/column lookup, not a self-contained normalization function.
- `0xc00ddda0..0xc00dde34`: source loads through B4 and destination stores
  through A4/A5, with byte count in A6. This looks like a byte-copy routine,
  consistent with state[34] copying coefficient defaults. There is no visible
  callback-table registration in this body.
- `0xc00cc94c` (documented state[7] target) can call `0xc00cc8c8` at
  `0xc00cc9d4`. That routine checks B14[98]: when nonzero it directly stores
  B1 at A4 (`0xc00cc946`). Otherwise it can publish data, set the flag at
  `0x11f03b1c`, and loop at `0xc00cc924..0xc00cc930` until it clears.
  This is a concrete wait path even with a valid callback pointer.
- The template writer is called at `0xc00ab614`; the precise custom `_init`
  invocation and runtime value of B14[98] have not been established here.

These are static observations, not a hardware diagnosis. In particular, a wait
on that flag is a hypothesis, not a measured freeze location. Next trace the
writers of B14[98], its data-page base, and the stock/custom initialization
entry paths. Establish the destination state and normalization chain before
attempting direct stores. Bypass initialization also needs a separate contract;
the experimental linker currently calls user knob handlers only.

## Diagnostic changes and validation

`matcheck` now requires `--params N --bypass 0|1`, checks every requested user
parameter against 11,22,... divided by 100, and checks params[0] without calling
`set_engaged` first. The count must match the manifest; this deliberately avoids
inferring user knobs from exported symbols. It is for the custom normalized
0..100 contract, not arbitrary stock effects with other parameter laws.

It separately reports snapshots after init and after handlers, rejects unreadable
or nonfinite values, and exits 1 for failed initialization, unsupported init
instructions, handler errors, insufficient handler calls, or mismatches in
either snapshot. Exit 2 means invalid CLI arguments. This is stricter than an
exploratory report: today's broken initialization should fail.

The expected bypass value is supplied explicitly because this rig cannot infer
the intended firmware load state. A pass only covers the emulated load state;
it does not establish both engaged and bypassed hardware behavior.

Three standalone Rust regression tests pass, covering raw-but-nonzero values,
wrong normalized values, NaN/infinity, missing/unreadable values, bypass, and the
ninth knob. Full Cargo checking is blocked by the absent external `../emu` and
`../formats` Ziddle crates. No effect binaries were rebuilt or flashed.

## Follow-up: direct-write flag and the actual init call site

The B14[98] trace changes the priority of the wait hypothesis. The firmware
explicitly enables direct writes around descriptor entry 1, not just around UI
edits. No executable files were changed in this follow-up.

### Reconstructed call path

1. `0xc00b86e4` prepares the six slot contexts, copies 264 bytes (6 × 44)
   into the raw table at `0xc009c1a0` (`0xc00b8712..0xc00b8724`), and calls
   `0xc00c3e00` at `0xc00b8728`.
2. `0xc00c3e00` loops slots 0–5. For each, it calls `0xc00c8e6c` to get
   `0x11f03000 + slot*0xd4`, then `0xc00c3c20` at `0xc00c3e22`.
3. `0xc00c3c20` reads the slot index from context[0] and requests descriptor
   entry 1 via `0xc00b056c(slot, 1)` at `0xc00c3c30`.
   The lookup computes descriptor base + entry_index*48. This matches the
   linker's 48-byte entries and init pointer at entry 1 + 0x1c.
4. `0xc00c3c48..0xc00c3c4c` stores **1** into B14[98].
5. It reacquires the context through `0xc00c8e6c`, loads entry[7] at
   `0xc00c3c70`, and branches to it at **`0xc00c3c74`**, with return address
   `0xc00c3c80`. This is the concrete init dispatch previously left unresolved.
6. Later it conditionally clears B14[98] at `0xc00c3cf4` or `0xc00c3d44`,
   depending on the outer-operation flag B14[150] bit 0. It can then invoke
   descriptor entry 0 (on/off), separately from init.

The entry-1 handling branch in `0xc00bb288` also reaches this same wrapper
(`0xc00bb398`); the generic dispatcher's later skip of entry 1 is not evidence
that entry 1 never dispatches through the larger operation.

There is no stock/custom distinction visible at this indirect call site.
Assuming the custom descriptor takes this path and B14 remains intact, its
handler's state[7] callback should see direct-write mode. The experimental
assembly saves B14 and does not explicitly change it in its prologue or call
block; this is a source inspection, not proof of register values on hardware.

### Other writes and the data-page base

Set/clear pairs also occur at:

| Set to 1 | Clear to 0 | Context |
|---|---|---|
| `0xc00b6d0c` | `0xc00b6d4c` | encloses calls to `0xc00b86e4` |
| `0xc00b898c` | `0xc00b89d4` | six-slot setup followed by `0xc00b86e4` |
| `0xc00c205c` | `0xc00c2264` | bulk setup followed by `0xc00b86e4` |
| `0xc00c2348` | `0xc00c24d0` | bulk setup followed by `0xc00b86e4` |

Startup sets B14 to `0xc00ef748` at `0xc00dd818..0xc00dd81c`, making
B14[98] correspond to `0xc00ef8d0` for that base (98 × 4 = 0x188).
Runtime context restoration also loads B14, so the base should still be
measured in a diagnostic rather than assumed globally.

### An additional stale ABI address

Tracing the template's actual register assignments confirms state[7] is
`0xc00cc94c` (A0 → B19 → A14 → state[7]). But **state[21] is
`0xc00ca380`, not `0xc00c8c80` as older notes say**:

- `0xc00c8b44..0xc00c8b64`: construct `0xc00ca380`, copy to B11.
- `0xc00c8d6c..0xc00c8d70`: copy B11 to A14 and store state[21].

The body at `0xc00ca380` performs float conversion/scaling with a branch table.
The proposed direct-init route must account for this operation; reading
state[31] and assuming its result is already the normalized DSP value is unsafe.

### Next diagnostic target

Do not toggle the global direct-write flag in custom code based on the wait
hypothesis. The firmware already sets it on the traced path. First verify the
actual failing binary's entry-1 target, context pointer, B14 and B14[98] at init
entry, then isolate read-knob, scaling and final-write stages. Compare the
coefficient-block setup omitted by the experimental init with stock LineSel.
The zero-call probe cannot validate those stages or the return path from a real
handler. Hardware cause remains unresolved; this trace narrows the assumptions.

## Binary inspection: absolute call targets were never relocated

The saved `build/probes/MatProb.ZDL` has SHA-256
`f745fba9e74e7dfcf3c2ed565ad2189c14134c9874f214ee809c962a26920dba`.
It contains the two-call guarded initializer (not P0). Its exact relationship
to a particular hardware trial is not independently recorded here.

At text VA 0x7e4/0x7e8 it loads **absolute 0x380** into A3, then branches
through A3 at 0x800. The second block loads **absolute 0x3cc** and branches at
0x840. The ELF text segment has link VA zero. Neither pair has an entry in
`.rela.dyn`; the only text relocation destinations are 0x8a4, 0x8a8, 0x8ac,
and 0x8b4 (the DLL descriptor/image setup).

Therefore these handler calls cannot follow a nonzero text load base. This is
a concrete linker defect and is consistent with P0 booting while the calling
versions freeze. It does not depend on callback availability or coefficient
setup. The previous assertion that emulation proved the instruction sequence
correct was too strong: code linked at zero can work at zero and fail when moved.
The external emulator's actual load base has not been checked in this pass.

### Fix and isolated candidate

The assembly now uses a direct PC-relative B.S2 at call-block+0x20, followed by
the existing ADDKPC return setup. The linker patches its signed displacement
using the actual init and handler link addresses. The branch starts on a
32-byte fetch-packet boundary; this is checked. The old address-load words are
NOPs, preserving the frame, guard, timing, and 64-byte block layout.

TI assembly regenerated the templates. The candidate was linked from the existing
MatProbe object into `build/probes/pcrel/MatProb.ZDL`, leaving the saved probe
and release effects untouched. Its SHA-256 is
`04d4779b634c5ceb80b56109562e971d73d4abfa39b220ef9f9f593d03d29c51`.

TI disassembly confirms:

- 0x800: B.S2 0x380; return remains 0x820.
- 0x840: B.S2 0x3cc; return remains 0x860.

Exactly six text instruction words differ from the saved probe: 0x7e4, 0x7e8,
0x800, 0x824, 0x828, 0x840. All bytes outside .text are identical. No new
runtime relocations were introduced; .fardata remains empty and the linker
reports zero applied object relocations.

`python3 -B -m unittest discover -s build/tests -v` passes three regression
checks: branch targets at zero and two nonzero text bases (including forward
and backward calls), unchanged zero-call frame, and invalid alignment/range
rejection. The template generator also checks the assembler-emitted branch
opcode and placeholder destination. `git diff --check` passes.

The candidate is **not hardware-verified** and materializing init remains off
by default for release effects. The next hardware experiment can now isolate
this specific relocation correction rather than alter firmware callback state.
Do not treat it as a proven parameter/bypass fix; other initialization
prerequisites may remain. No hardware interaction or release rebuild occurred.

## Hardware confirmation and Rooms candidate

The owner reports the corrected MatProb candidate loads without freezing,
controls work at multiple positions in **all six slots**, Gain=0 is silent,
and saved settings remain audible after leaving/re-entering patches and after
a power cycle. The Patch Editor was disconnected. This verifies the MatProb
relocation correction on the project's MS-70CDR; it does not yet qualify the
full release pack.

A five-parameter Rooms candidate is now built from current source:

```bash
python3 -B src/custom/rooms/build.py --materialize-init --output-dir build/probes/rooms-init
```

Artifact: `build/probes/rooms-init/Rooms.ZDL` (10,790 bytes).
SHA-256: `a5741449a01733e1691824b396be9b0e128f1e8965f01061dfdba41c487646d9`.

The build has zero .fardata, no outlined .text helpers, and zero applied object
relocations. TI disassembly verifies all five init branches, including three
synthesized handlers: 0x1b60→0x1140, 0x1ba0→0x118c, 0x1be0→0x1320,
0x1c20→0x1500, 0x1c60→0x16e0. The three linker regression tests pass.
`dist/Rooms.ZDL` is unchanged; initialization remains opt-in.

Rooms hardware validation was subsequently confirmed by the owner ("Yup all works")
after the requested five-control, slot, patch-change and power-cycle checks with
PE disconnected. This confirms MatProb and Rooms; the other release effects
have not yet been validated with materializing init. Full-pack enablement and
rebuild remain pending.

The test instructions used were: remove the installed Rooms before adding
this candidate (same effect ID/version). Set distinct audible controls, save,
disconnect PE, then test patch return in slots 1–6 and a power cycle. Include
Freq, Depth, and Mix so synthesized handlers are covered. Confirm Mode as well
as decay and wet/dry behavior; do not confuse silent Mix=0 wet output with a
boot failure. No hardware writes were performed by the agent.

## Release rollout completed

All 22 release build scripts now enable the corrected PC-relative init. A full
`build_all.py` run completed successfully and refreshed both the JSON and inline
Patch Editor effect databases. `build/verify_release_init.py` passes for every
release file: init body, descriptor targets, rebased calls, handler prologues,
manifest parameters/IDs, exact release set and both editor database copies.
The build log has no WARNING/SKIP/FAILED entries, no nonzero source .fardata,
and no nonzero applied object relocation counts. Three regression tests pass.

The pack is built, not universally hardware-qualified: MatProb and Rooms alone
have the owner-confirmed tests above. The Patch Editor replay behavior remains
unchanged for older installed effects. Read-only follow-up findings (zero-value
fallback, overlapping editor transactions, stale Apply fields and permissive
unresolved-link handling) await approval in `RELEASE-INIT-AUDIT.md`.
Release hashes are saved in `RELEASE-INIT-VERIFICATION.json`. No commits or
hardware writes were performed.

## 2026-09-10: follow-up fixes and PE UI audit

The four release audit findings now have fixes: valid-zero normalization and
legacy scaling cleanup, loaded-control seeding in Howl/Dustbox, exclusive PE MIDI
transactions with verified dirty-field Apply, and fatal unresolved/unsupported
linker relocations. All 22 effects rebuilt and passed static release verification.
Six Python and eight Node regression tests pass. Offline browser checks covered
Rooms import and keyboard knob endpoints. See [RELEASE-INIT-AUDIT.md](RELEASE-INIT-AUDIT.md)
for the UI findings, fixes, and remaining hardware validation. These new binaries
are not covered by the earlier owner hardware confirmation.

## Oxide/Spool voicing follow-up

User reported the previous Rooms/PE checks working. Version 1.01 Oxide and Spool
now add drive-level compensation and a progressive feedback range, respectively,
with quieter starting defaults. See TAPE-VOICING-PASS.md for exact changes, host measurements,
and hardware listening checks. No hardware validation of this new voicing yet.

### 2026-09-11 — Stasis follow-up

Stasis v1.01 adds a sixth materialized Capture parameter (0 stomp / 1 live /
2 hold). Release verification and PE database sync pass. This is a DSP/control
revision, not evidence of another init-relocation bug. Multiple-instance host
capture tests pass; the reported failure of later pedal slots to retrigger still
requires hardware reproduction. Details: [Stasis revision](STASIS-REVISION.md).
