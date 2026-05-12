# State ABI Progress Log

Date: 2026-05-12

This log captures each concrete step toward the state model needed for 1:1
Airwindows ports. The rule is simple: if we learn something or build a probe,
write it down here before relying on it later.

## 2026-05-12: Current Blocker

State-heavy Airwindows effects cannot be 1:1 until the Zoom host state ABI is
mapped. `StereoChorus` alone needs two `int[65536]` delay lines plus multiple
history scalars. Stock ZDLs do not carry large writable ELF memory, and large
custom `.fardata` has frozen hardware before, so static delay arrays are not a
safe release strategy.

## 2026-05-12: PDF Findings

The TI manuals in `docs/` document the C6000 toolchain and startup rules, not
Zoom's private effect host. Useful constraints:

* Use `--mem_model:data=far` so custom globals do not rely on `B14`/`DP`.
* Reject near-data relocations such as `R_C6000_SBR_*` until DSBT/GOT support
  is deliberately implemented.
* Do not assume `.bss`, `.far`, `.cinit`, constructors, stack setup, or heap
  are initialized the way a normal C program would initialize them.
* Treat `malloc`/`calloc` as unavailable in ZDL audio code until proven.

## 2026-05-12: Stock Corpus Findings

The 830-file stock ZDL pass found no `PT_LOAD` segment where `memsz > filesz`.
Most `.fardata` sections are 24 bytes, only 80 files exceed that, and the
largest observed `.fardata` is 220 bytes. This supports the hypothesis that
large delay/reverb history is host-provided rather than embedded as writable
ELF data.

## 2026-05-12: Stock Audio Entry Clue

`build/disassemble_zdl.py` now extracts stock ELFs, runs TI `dis6x`, and
summarizes likely `ctx[...]` root reads near audio entry.

Early evidence:

| Effect | Extra fields beyond the known minimal map |
|---|---|
| `STCHO` / `CHORUS` | `ctx[2]`, `ctx[3]`, `ctx[13]`, `ctx[14]` |
| `DELAY` | `ctx[2]`, `ctx[3]` |
| `HALL` | `ctx[2]`, `ctx[3]` |

Working hypothesis: these are host-managed state/scratch/delay descriptors or
related runtime structures. They must be mapped on hardware before exact
Airwindows delay, chorus, tape, or reverb ports.

## 2026-05-12: Probe 1 - `CtxMap`

Added `src/airwindows/ctxmap/`, a hardware-only ABI mapper.

Purpose:

* Inspect `ctx[0..15]` one word at a time.
* Select a bit inside the word.
* Emit a square-wave tone if that bit is set.
* Never dereference the selected word.

Controls:

| Knob | Range | Meaning |
|---|---:|---|
| `Slot` | 0-15 | `ctx[]` index to inspect |
| `Bit` | 0-31 | bit inside the selected 32-bit word |
| `Level` | 0-100 | audible probe tone level |

Hardware test procedure:

1. Build `dist/CtxMap.ZDL` and load it on the pedal.
2. Feed silence into the pedal or record its output.
3. For each `Slot` from 0 to 15, sweep `Bit` from 0 to 31.
4. Record `1` when the tone is present and `0` when it is absent.
5. Reconstruct each `ctx[Slot]` word from the 32 bits.
6. Repeat after bypass, parameter edit, preset switch, and duplicate-instance
   tests.

Expected next evidence:

* Which fields are stable constants.
* Which fields look like addresses.
* Which fields change per instance or per preset.
* Whether suspected stock fields (`ctx[2]`, `ctx[3]`, `ctx[13]`, `ctx[14]`)
  are valid, stable, and per-instance.

Recording template:

| Condition | Slot | Bits 31..0 | Reconstructed word | Notes |
|---|---:|---|---|---|
| load, effect on | 0 | | | |
| load, effect on | 1 | | | |
| load, effect on | 2 | | | suspected stock state field |
| load, effect on | 3 | | | suspected stock state field |
| load, effect on | 13 | | | suspected stock modulation field |
| load, effect on | 14 | | | suspected stock modulation field |

Build result:

* Command: `python3 -B build_all.py ctxmap`
* Output: `dist/CtxMap.ZDL`
* `.audio`: 448 bytes
* `.fardata`: 4 bytes (`gPhase` tone counter only)
* ZDL size: 5382 bytes
* Python syntax check: `python3 -B -m py_compile build/zdl.py
  build/disassemble_zdl.py src/airwindows/ctxmap/build.py build_all.py`

## Next Probe

After raw words are mapped, build a read-only pointer probe for pointer-looking
slots. It should dereference only one selected candidate field at a time, emit
the low bits of word `0`, and include a NOP/silence fallback build for quick
hardware recovery.
