# The 3-param linker bug

**Status:** open. Workaround available via [src/airwindows/tapehack/build_via_template.py](../src/airwindows/tapehack/build_via_template.py).

## Symptom

When our linker emits a ZDL with exactly 3 user-facing parameters
(descriptor entries: OnOff + name + 3 knobs), the MS-70CDR firmware
falls back to a 2-knob render mode after entering edit mode. The third
descriptor entry is silently dropped from the UI; turning hardware
knob 3 calls its (broken) edit handler.

1- and 2-param plugins from the same linker work correctly. Stock
3-param effects (Exciter, OptComp, ZNR) work correctly. A renamed
clone of stock Exciter ([dist/TapeHKEx.ZDL](../dist/TapeHKEx.ZDL))
shows 3 knobs on the same hardware. So:
* Pedal/firmware can render 3 knobs ✓
* Our linker output for 3 params has *something* malformed that
  silently downgrades the render path.

## Hardware tests already eliminated as the cause (2026-05-10)

Each of these was flashed as the only delta and produced "still 2 knobs":

| Hypothesis tested | Result |
|---|---|
| AIR `mix_edit` blob poisoning the descriptor (replaced with NOP_RETURN) | no fix |
| Last-entry `pedal_flags = 0x04 → 0x14` alone | no fix |
| Knob screen positions `(14,34)/...` → AIR's `(21,36)/(45,36)/(69,36)` | no fix |
| 3-param sentinel pattern `pedal_flags=0x14` AND `pedal_max=max` (matches Exciter / OptComp / ZNR exactly) | no fix |
| Dynsym ordering: STB_LOCAL syms before STB_GLOBAL, `.dynsym sh_info = first_global_idx` | no fix |

The dynsym fix was kept (ELF spec compliance, matches stock layout,
won't hurt) even though it didn't resolve this specific bug.

## What we know about the firmware

`firmware/Main.bin` is a TI SYS/BIOS C6x firmware wrapped in TIPA
container format. Strings from `Main.bin` reveal relevant function
names:

* `Task_MainApp`, `Task_UpdateUI`, `Task_QFuncService`
* `Swi_Encoder` — knob-encoder ISR
* `Semaphore_FxEdit` — taken when entering edit mode (probably the
  trigger for the buggy 3-param walk)
* `Event_UpdateUI`
* `Hwi_AudioIOHandler`, `Swi_AudioProcess`
* DLL loader error tags: `DLE_DLL_NOT_FOUND`, `DLE_DLL_BUSY`

The TIPA wrapper has not been parsed; raw code chunks live between
"YSX" markers in `Main.bin`. The largest chunk
(file offset `0x5489..0x49675`, ~278 KB) is likely the bulk of the
SYS/BIOS-based OS. Disassembly with `dis6x` is feasible once the
TIPA structure is understood.

## Suggested investigation order if resumed

1. Parse the TIPA chunk format — header decoding, chunk types, code
   load addresses. Cross-check with TI's published SYS/BIOS firmware
   image format (if available) or RE another Zoom firmware to
   triangulate.
2. Extract the largest code chunk; run `dis6x` to get assembly.
3. Locate `Semaphore_FxEdit` references — the function that pends on
   it is where edit-mode rendering kicks off.
4. Trace back to the SonicStomp descriptor walker; identify what
   condition trips the 2-knob fallback.
5. Compare that condition against our 3-param ZDL output and fix the
   linker.

## Working artifacts produced during the investigation

* [dist/AirCtl.ZDL](../dist/AirCtl.ZDL) — minimally-modified stock AIR
  (renamed, fxid bumped). Confirms 6-param render works on hardware.
* [dist/TapeHKEx.ZDL](../dist/TapeHKEx.ZDL) — minimally-modified stock
  Exciter (renamed, fxid bumped). Confirms 3-param render works.
* [src/airwindows/tapehack/build_via_template.py](../src/airwindows/tapehack/build_via_template.py)
  — splices a compiled `.audio` section into a stock 3+ param ZDL as
  a template. Output runs but knob ranges follow the template's edit
  handlers, not the user's intent — needs handler synthesis to be
  truly drop-in.
