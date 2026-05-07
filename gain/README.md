# GAIN — first ground-up plugin for the v2 builder

The simplest possible custom-built ZDL: pass-through with one Level knob.
Built end-to-end through the v2 full-ELF linker pipeline. No template
ZDL, no opcode patching — every byte of the output ZDL is generated
from `gain.c` + `manifest.json` + the linker's empirical knowledge of
the ZDL format.

This plugin's purpose isn't audio quality. It's to validate the v2
pipeline and to **answer the open ABI question** that broke v1's
multi-knob ToTape9 port.

## Files

| File             | Purpose                                                    |
|------------------|------------------------------------------------------------|
| `gain.c`         | Audio function source — single `Fx_FLT_GAIN` in `.audio`   |
| `manifest.json`  | Effect metadata, gid/fxid, knob descriptors                |
| `build.py`       | `cl6x` → `linker.link()` → `GAIN.ZDL`                      |
| `GAIN.ZDL`       | Build artifact (3192 bytes; structurally matches v1's TOTAPE9_AUDIO) |

## Build

```bash
python3 gain/build.py
```

Requires the local TI compiler at
`/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS/`.

What it does:
1. `cl6x --c99 -O2 --mem_model:data=far -c gain.c -o gain.obj`
2. Loads `gain.obj` into `build/linker.py`, which synthesises a complete
   ZDL ELF (.text + .const + .fardata + dynamic linking metadata + Zoom
   76-byte header).
3. Writes `gain/GAIN.ZDL`.

## What the DSP does

```c
gain = params[5] * params[4] * params[0]      // raw_level / max * onoff
for each sample s in Fx:
    Output[s] += s * gain
```

* When ON at Level=100: full pass-through, doubled (Output += Fx).
* When ON at Level=50:  half-volume contribution (Output += 0.5 * Fx).
* When ON at Level=0:   silent contribution (Output += 0).
* When OFF: silent regardless of Level (`params[0] == 0.0` zeros gain).

Note: this is *additive* gain — it adds to whatever upstream effects
already wrote into Output. That's the LineSel "trick book" convention
(see ABI.md §7) — all stock effects sum into Output rather than
overwriting.

## The experiment this plugin is designed to run

The pagination/knobs bug in v1's ToTape9 boiled down to one open
question: **does the firmware auto-populate `params[5..]` from the
visible knob state, or do the per-knob `_edit` handlers have to write
values into the params table themselves?**

GAIN, with one knob and a `NOP_RETURN` `_edit` handler (just like v1's
TOTAPE9_AUDIO), is the smallest possible test. Three outcomes:

| What you observe on the unit             | What it tells us                                                                |
|------------------------------------------|---------------------------------------------------------------------------------|
| Level knob audibly changes the signal    | Firmware auto-populates `params[5]`. NOP handlers are fine for ≤3 knobs.        |
| Knob does nothing (silent or full pass)  | Handlers must do real work. Multi-page is impossible until we disassemble one.  |
| Pedal freezes / reboots / no audio       | Linker bug. Compare GAIN.ZDL byte-by-byte against v1's TOTAPE9_AUDIO.ZDL.       |

If outcome 1: proceed to the 3-knob test (next plugin) to confirm
single-page behavior, then to a 6-knob plugin to settle multi-page.

If outcome 2 or 3: pause new-plugin work, reverse-engineer LineSel's
`_efx_edit` handler from disassembly to learn the required handler
shape, write the handler in C, recompile.

## Where to flash

Same path as v1:

1. The flashing tool the user already has working (modified Zoom Effect
   Manager / DFU loop).
2. Add the file to the firmware bundle's effect list:
   `XXX;GAIN;GAIN.ZDL;;MS-50G;MS-60B;MS-70CDR;G1on;B1on;GAIN EN;GAIN RU;FLTR;0x02;1.00`

(Replace `XXX` with the next free index.)

## What the linker did

Generated structure (verified to match v1's known-bootable TOTAPE9_AUDIO):

* **4 PT_LOAD** segments: .text r-x at 0x0, .const r-- at 0x80000000,
  .fardata rw- at 0x80000200, PT_DYNAMIC.
* `.fardata` `memsz == filesz == 24` (KNOB_INFO only). [v1-empirical:
  any larger and pagination breaks.]
* `effectTypeImageInfo` padded to **exactly 212 bytes**, with **3 knob
  slots** (not the 1 we have parameters for). Firmware paginates by
  walking the descriptor table and overlaying onto these fixed slots.
* `_infoEffectTypeKnob_A_2` = `{20, 15, 11, 0, 2, 0}`.
* `Dll_GAIN` body = verbatim copy of NoiseGate's 200-byte Dll function.
* SONAME = `ZDL_FLT_GAIN.out` (matches `gid=0x02`).
* Descriptor: OnOff + GAIN + Level, last entry `pedal_flags = 0x04`
  (end-of-table sentinel).
* All `func_ptr` / `audio_ptr` slots are 0 on disk; resolved at load
  time via `.rela.dyn` ABS32 entries.

## Smoke-build option

If the unit freezes on FX-select, set `"audio_nop": true` in
`manifest.json` and rebuild. The audio function gets replaced with a
canonical NOP_RETURN sequence after linking — the unit will still
boot and the effect still appears in the menu, but no DSP runs.
This bisects "linker bug" vs. "audio function bug".

This is exactly how v1's TOTAPE9_AUDIO.ZDL was made — and that one
flashed and booted, so the audio-NOP path is the known-good baseline
for our linker.
