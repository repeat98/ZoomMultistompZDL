> **RESOLVED 2026-09-10.** Parameter materialization works. All 22 release
> builds enable PC-relative parameter initialization, the full build and
> binary/manifest/editor-database checks pass, and the owner reports the rebuilt
> pack working on the MS-70CDR. Slots 4–6 work as a consequence.
>
> §2 below is kept as the investigation record — four `_init` attempts froze the
> pedal before the cause was found, and the reasoning that went wrong is worth
> reading before anyone touches `_init` again. See
> [RELEASE-INIT-AUDIT.md](docs/RELEASE-INIT-AUDIT.md) and
> [PARAM-INIT-INVESTIGATION.md](docs/PARAM-INIT-INVESTIGATION.md) for the
> rollout and the actual diagnosis.

# Handoff — state of play, 2026-09-10

Written for someone (or some model) picking this up cold. It covers what changed
recently, what has already been tried and ruled out, and how to test without
bricking the pedal.

**§2 is history, not an open bug** — see the banner above.

---

## 1. Current state

**Hardware:** Zoom MS-70CDR, firmware 2.10. Toolchain: TI CGT v8.5.0 at
`/Applications/ti/ti-cgt-c6000_8.5.0.LTS`.

**Nothing is committed.** The last commit is `c264121`. Everything below is in
the working tree. That is deliberate — the repo owner commits, not the agent.

Uncommitted work, roughly in order of how finished it is:

| Area | State |
|---|---|
| Oxide (`totape9.c`) knob rewiring + dry path | done, not heard on hardware |
| Howl output trim | done, not heard on hardware |
| Rooms `Depth` (ROOM-mode size) | done, not heard on hardware |
| Rewire frequency shifter + new defaults | done, image rejection measured at −51 dB |
| **Gyre** (new effect, `src/custom/gyre/`) | done, never heard on hardware |
| Patch editor (`tools/patch_editor.html`) | done, verified in browser + on pedal |
| Cover art regenerated (VHS theme) | done; **format question still unanswered** |
| `build/init_materialize.asm` + linker support | v4, **freezes the pedal**, off by default |
| `tools/emulator/` test rig | done |
| Docs | this pass |

**Unanswered question the owner has been asked twice:** the regenerated cover
art is ~15 MB of PNG. JPEG q88 is ~6× smaller but needs file renames and README
edits. Nobody has decided.

**Hardware listening backlog** — none of these have been heard on the pedal:
Gyre, Oxide (rewired knobs), Howl (trim), Rewire (new defaults), Rooms (Depth),
Dustbox, Stasis, Spiral/Hydra tempo lock.

---

## 2. SOLVED — params were not materialized at patch load (investigation record)

### What the user sees

Load a patch containing a custom effect. The pedal's screen shows the saved knob
values. The slot passes **dry audio**. Touch any knob and it springs to life,
correctly, at the value already displayed.

### Why

After a patch load the DSP reads `params[5..N]` as **zeros** — including
`params[0]`, the bypass flag, so the audio function returns on its first
instruction. Stock effects escape this because their `_init` calls their own edit
handlers at load. Ours emits a `NOP_RETURN`.

Full write-up: **[docs/INIT-MATERIALIZATION.md](docs/INIT-MATERIALIZATION.md)**.
Sections 9–11 are this session's and are the current state; 1–8 are older
analysis, and §2's "stock materializes by calling its edit handlers" is true but
see §11.2 for the catch.

### This is also why slots 4–6 are unusable

The two look like separate bugs and are not.

The firmware honours live `0x31` param edits only on **slots 1–3**. In 4–6 the
identical message is ignored — for stock effects too. Stock effects still work
there because the editor falls back to store+reload, and a reload re-materializes
stock params via their `_init`. Ours cannot survive a reload, because that is
precisely the broken path.

So in slots 4–6 there is no `0x31` escape hatch and no working reload, and **no
editor-side workaround is possible**. Fixing `_init` is the only route.

### What has been ruled out (four freezes, one clean bisect)

| Attempt | Result |
|---|---|
| v1 — ctx held in A10 across handler calls | freeze on boot |
| v2 — ctx on the stack instead | freeze on boot |
| v3 — v2 + full callee-saved set saved (`__push_rts` equivalent) | freeze on boot |
| v4 — v3 + skip the call when `ctx[31] == 0` | freeze on boot |
| **P0 — the same frame with ZERO calls between prologue and epilogue** | **boots fine, all slots** |

P0 is the one that mattered. It proves the frame, the stack discipline, the
`ADDKPC` return arithmetic and the descriptor wiring are all correct, and puts
the fault entirely in the handler calls.

### Current investigation: unrelocated init calls found

The saved two-call MatProbe loads absolute handler addresses 0x380/0x3cc with
no relocation records. Those calls break when the text segment moves. The linker
now emits PC-relative branches; an isolated candidate is in
`build/probes/pcrel/MatProb.ZDL`. TI disassembly and three relocation regression
tests pass. The owner confirmed no freezes, working controls and saved settings in all six
slots and after power cycling, with PE disconnected. Release init remains
opt-in. A five-knob Rooms candidate is ready at
`build/probes/rooms-init/Rooms.ZDL`; the owner has now confirmed the requested hardware checks pass. Full-pack enablement and rebuild are complete; remaining hardware listening
checks are pending.

The earlier claim that state[7] must be unpopulated during init was too strong.
Fresh disassembly confirms stock LineSel's init calls its state[7]-delegating
handlers after a state[34] setup call. Firmware state[7] also has a path that
waits on a shared flag; a valid pointer does not establish readiness.

See [PARAM-INIT-INVESTIGATION.md](docs/PARAM-INIT-INVESTIGATION.md) for exact
addresses, diagnostic changes, and remaining questions. The follow-up trace found the init dispatch at `0xc00c3c74`: firmware sets
B14[98] to 1 before calling entry 1. Thus a wait is not expected on that path
with intact context/B14; the next target is the failing binary’s actual entry
state and handler stages. Direct
materialization remains an option only after checking normalization, destination
state, and bypass behavior.

### The editor-side workaround that IS shipping

`tools/patch_editor.html` replays every knob in slots 1–3 as live `0x31` edits on
every patch load — the "wiggle a knob" cure, automated. Verified working on
hardware. See [docs/INIT-MATERIALIZATION.md](docs/INIT-MATERIALIZATION.md) §9 for
the three non-obvious implementation details.

It does **not** cover slots 4–6, footswitch patch changes, or anyone not running
the editor.

---

## 3. How to test

Full detail in **[docs/EMULATOR-TESTING.md](docs/EMULATOR-TESTING.md)**. The
short version:

**Emulator (free, safe, and not sufficient).** Ziddle runs our ZDLs headlessly.
`tools/emulator/matcheck` reports whether `_init` completes and whether params
materialized. It is authoritative about instruction semantics and **worthless
about firmware readiness** — it passed all four builds that bricked the pedal,
because it models `ctx[7]`/`ctx[31]` as always present and does not model
`ctx[34]`/`ctx[35]` at all.

**Disassembly (free, safe, underused).** `build/disassemble_zdl.py` extracts and
disassembles any ZDL's ELF, ours or stock. `stock_zdls/` has ~830 of them. The
single most productive hour of the `_init` work was diffing our generated handler
against `Fx_MOD_VintageCE_comp_edit`. Verify what the build *actually emitted*,
not what the template says.

**Hardware (expensive).** Every freeze costs a recovery cycle: Effect Manager,
remove the effect, rewrite. If a patch references a bad effect and the pedal
hangs on the boot screen: power off, hold the **leftmost knob pressed in**, power
on → `All INITIALIZE` → footswitch.

**Bisect rather than flash candidate fixes.** Three "candidate fixes" cost three
freezes and taught nothing; one probe that did nothing at all located the fault.
`ZDL_MATERIALIZE_INIT_MAX_CALLS=0` builds exactly that probe.

**Fail safe.** `MatProb` (fxid 496) defaults Gain to 0, so an unmaterialized load
is *silent* rather than ambiguous. Probes live in `src/hardware_probes/`, build
to `build/probes/`, and must never reach `dist/`.

### Build switches

```bash
python3 -B build_all.py                       # 22 release effects -> dist/
python3 -B build_all.py rooms                 # one effect
python3 -B build_all.py --all                 # + probes -> build/probes/

ZDL_MATERIALIZE_INIT=1 python3 -B src/custom/rooms/build.py
#   emit the materializing _init for every effect in the build. OFF by default:
#   this _init freezes the pedal.

ZDL_MATERIALIZE_INIT=1 ZDL_MATERIALIZE_INIT_MAX_CALLS=0 \
  python3 -B src/hardware_probes/matprobe/build.py
#   ...capped to N handler calls. 0 = the frame only. For bisecting.

python3 -B build/gen_init_materialize.py           # show the _init byte templates
python3 -B build/gen_init_materialize.py --write   # regenerate them into linker.py
```

`build_all.py` re-extracts the patch editor's effect database at the end, so the
editor cannot go stale against `dist/` — it silently did, twice.

---

## 4. Other things worth knowing

**Chrome 152 has a Web MIDI input regression.** Output works, input delivers
nothing, no error. Proven with a bare test page (`tools/midi_check.html`) and a
Python control. **Use Opera.** A lot of time went into debugging our own code
before this was identified.

**`0x31` slot rule.** Live param edits are honoured on slots 1–3 only. ToneLib
has no live path either — a capture of one knob drag showed 32 patch dumps and
zero `0x31`. It just re-instantiates constantly.

**The editor is a single self-contained HTML file** and its effect database is
inlined. Regenerate with `build/extract_effect_db.py` (or just run `build_all.py`).

**Zoom Effect Manager holds the MIDI port exclusively.** If the editor says the
pedal did not respond, check that first.

**Safe-DSP rules are not style guidance** — each one is a freeze that happened:
no `switch`, no runtime divide or modulo, no static arrays, no `.fardata`, zero
relocations, no float→unsigned casts. A clean build prints `.fardata: 0 bytes`
and `Applied 0 .obj relocations`. See [docs/SAFE-DSP-RULES.md](docs/SAFE-DSP-RULES.md).

**`static inline` is only a hint.** Past a call-site threshold the compiler
outlines helpers into `.text`, which freezes, and it does so *silently*. Any
`.text` outside `.audio` is the tell. Pin helpers with `FUNC_ALWAYS_INLINE`.
Rewire built clean at 7 knobs and outlined at 8 with no warning.

---

## 5. Where to look

| File | Why |
|---|---|
| [docs/PARAM-INIT-INVESTIGATION.md](docs/PARAM-INIT-INVESTIGATION.md) | how the materialization bug was actually diagnosed and fixed |
| [docs/RELEASE-INIT-AUDIT.md](docs/RELEASE-INIT-AUDIT.md) | the 22-effect rollout and four follow-up defects |
| [docs/INIT-MATERIALIZATION.md](docs/INIT-MATERIALIZATION.md) | investigation record for the same bug; §9–11 include conclusions later shown wrong |
| [docs/EMULATOR-TESTING.md](docs/EMULATOR-TESTING.md) | how to test, and what testing cannot tell you |
| [docs/EDIT-HANDLER-ABI.md](docs/EDIT-HANDLER-ABI.md) | why our handlers delegate to `ctx[7]` |
| [docs/SAFE-DSP-RULES.md](docs/SAFE-DSP-RULES.md) | the freeze classes |
| [docs/LOADER-SAFETY.md](docs/LOADER-SAFETY.md) | catalogued freeze causes |
| [docs/MIDI-PARAM-EDIT.md](docs/MIDI-PARAM-EDIT.md) | SysEx protocol, the slot 1–3 rule |
| [build/linker.py](build/linker.py) | `.obj` → `.ZDL`; `materialize_init` lives here |
| [build/init_materialize.asm](build/init_materialize.asm) | the candidate `_init`, with its full history in the header |
| [tools/emulator/](tools/emulator/) | the headless test rig |
| `stock_zdls/` | ~830 stock ZDLs — ground truth for everything (local only, [docs/STOCK-FILES.md](docs/STOCK-FILES.md)) |

## 2026-09-10 follow-up fix pass

Four audit findings fixed and PE UI audited; see docs/RELEASE-INIT-AUDIT.md for
current results and limitations. Full release pack rebuilt, six Python and eight
Node tests pass. PE build stamp is 2026-09-10e. No hardware writes or commits.
Next: owner hardware validation of new zero/scaling/cached-param fixes and PE
Apply/Store/rapid-selection behavior. Earlier confirmations cover the init fix.

## Oxide/Spool voicing follow-up

User reported the previous Rooms/PE checks working. Version 1.01 Oxide and Spool
now add drive-level compensation and a progressive feedback range, respectively,
with quieter starting defaults. See docs/TAPE-VOICING-PASS.md for exact changes, host measurements,
and hardware listening checks. No hardware validation of this new voicing yet.

## Stasis revision — 2026-09-11

User approved Stasis corrections after field feedback. Built `dist/Stasis.ZDL`
v1.01, synced PE databases. See `docs/STASIS-REVISION.md` for controls, migration,
MIDI constraints and hardware acceptance steps. Added Capture (0 stomp / 1 live /
2 hold), true wet blend only during hold, transparent stereo idle, short ramps,
and corrected loop seam. Host four-instance tests pass; actual reported later-slot
retrigger failure remains unconfirmed on hardware. Explicit mode ignores bypass
and must be released with Capture=1. All 10 Python and 13 PE Node tests pass;
release init/metadata verification passes. No commits or pedal writes.

### Stasis 1.02 scaling correction

User reports Capture=1 silent with slot ON and Mix=100. Corrected mistaken
max-relative Capture decode: cloned LineSel handlers use UI/100, so 1/2 are
.01/.02, not .5/1. Updated actual DSP host-test inputs and rebuilt Stasis/PE DB.
See docs/STASIS-REVISION.md. Await pedal confirmation; no pedal writes.
