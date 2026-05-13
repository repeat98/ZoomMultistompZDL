# The 3-param linker bug

**Status:** likely fixed in linker; pending final hardware confirmation.
Workaround available via [src/airwindows/tapehack/build_via_template.py](../src/airwindows/tapehack/build_via_template.py).

## Likely root cause found (2026-05-11) <--- YES THIS WAS

The linker copied the `Dll_NoiseGate` entry stub verbatim. That stub
stores `4` into the host-return struct, which is the descriptor entry
count for a two-user-param effect:

`OnOff + effect-name self-entry + 2 params = 4`.

The edit-mode parameter list uses this DLL-declared descriptor count,
not `effectTypeImageInfo`. This explains the exact hardware symptom:
the preview image can show 3 knobs, audio can run, but edit mode only
walks enough descriptor entries to render two user parameters.

Stock comparisons:

* `Dll_NoiseGate` writes `4` for 2 user params.
* `Dll_Exciter` / `Dll_OptComp` write `5` for 3 user params.
* `Dll_GraphicEQ` writes `9` for 7 descriptor user params.

`build/linker.py` now patches the DLL stub to write
`2 + len(params)` instead of the copied NoiseGate constant.

## Symptom (clarified 2026-05-11)

When our linker emits a ZDL with exactly 3 user-facing parameters:

* **Image preview (static knob rendering):** all 3 knobs visible. ✓
* **Normal-mode hardware control:** the 3rd hardware knob DOES bind to
  the 3rd descriptor entry — turning it modifies its parameter. ✓
* **Edit-mode parameter list:** only 2 of 3 parameters render (the
  first two). The third is dropped. ✗
* **No pagination indicator** is shown (single page expected for 3
  params — that part is correct).

So the bug is in the **edit-mode parameter-list iterator** — a code
path separate from both imageInfo-driven knob rendering AND the
imageInfo→descriptor knob-binding logic, both of which work fine.

Earlier sessions misdescribed this as "2-knob fallback" / "firmware
re-renders 2 knobs" — that was conflating the preview UI (which works)
with the edit-mode list (which doesn't). The clarification narrows
what we're hunting for: a single function that walks the descriptor
sequentially to build the per-param list, and silently drops our 3rd
entry while accepting Exciter's third entry.

Maybe we don't set default values for the parameters and they are omitted / not rendered because of this? In the image info the third knob actually moves when we tweak the hardware knobs, but once we go into edit mode it only renders the first two parameters.

1- and 2-param plugins from the same linker work correctly. Stock
3-param effects (Exciter, OptComp, ZNR) work correctly. A renamed
clone of stock Exciter (`dist/TapeHKEx.ZDL`, historical diagnostic artifact no
longer shipped in the clean release `dist/`)
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
| EABI fixes per SPRAB89B §14.4.3: visibility `STV_HIDDEN`/`STV_PROTECTED` + `.c6xabi.attributes` section | no fix |
| `effectTypeImageInfo +0x18 = 32` (Exciter / OptComp pattern) instead of 28 (LineSel) | no fix |
| Last-entry `default != max` (5/5 stock 3-param effects always differ) | no fix |
| Last-entry full byte-match with Exciter (`max=150`, `default=100`, `pedal_max=150`, `flags=0x14`) | no fix |
| Entry [1] `+0x28` = 20.0f (CPU-cost field; 5/5 stock effects non-zero) — kept as legitimate convention but didn't fix the bug | no fix |

The dynsym + EABI fixes were kept (ELF spec compliance, matches stock layout,
won't hurt) even though they didn't resolve this specific bug.

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

## Firmware RE progress (2026-05-11)

The TIPA wrapper is now fully understood and the firmware is being
disassembled cleanly. Reusable scaffolding lives in `firmware/`:

* `firmware/wrap_for_dis6x.py` — wraps each extracted TIPA code chunk
  as a minimal C6x ELF object with `.c6xabi.attributes` and
  `.TI.section.flags` lifted from a fresh `cl6x` output. **Without
  those two sections, dis6x can't decode the firmware's 16-bit
  compact instructions** — ~63% shows up as `.word`. With them,
  dis6x decodes ~99% cleanly. The probe attribute blobs are saved
  next to the wrapper as `firmware/probe_c6xabi_attrs.bin` and
  `firmware/probe_TI_section_flags.bin`.
* `firmware/extracted/` — raw `.bin` chunks named by load address +
  `.out` ELF wrappers ready for `dis6x -mv6740`.
* `firmware/extracted/main_os.dis` — full 64K-instruction
  disassembly of the 278 KB main OS code blob (load addr
  `0xc009dfc0`).

### Identified functions in the descriptor handling code path

* **`0xc00bb600` — `walk_descriptor(slot_idx, declared_count, ...)`**
  This is the outer descriptor walker. It loops counter A12 from 0,
  calling `get_entry(slot_idx, A12)` each iteration, reading
  `*entry[11]` (= pedal_flags at byte +0x2C), AND-ing with `0x04` and
  exiting when the sentinel is found OR A12 reaches 11.

  After the loop it does several post-walk checks:
  - `if (walked_count < declared_count)` → branch to `0xc00bb6ec`
    (likely the 2-knob fallback path)
  - `if (effect_type_code == 4 && declared_count == 9)` → special path
  - etc.

* **`0xc00b056c` — `get_entry(slot_idx, entry_idx)`**
  Returns a pointer to descriptor entry `entry_idx` for the effect
  loaded in slot `slot_idx`. Looks up the loaded DLL's descriptor base
  from a global table at `0xc0064e04` (28-byte stride per slot), then
  adds `entry_idx * 48` (the 0x30-byte SonicStomp entry stride).

* **`0xc00b05cc` — `effect_type_for_slot(slot_idx)`**
  Tiny 4-instruction table lookup:
  `return globals[0xc0064ec0 + slot_idx*4]`. Returns a small integer
  effect-type code. The walker checks if it equals 4.

* **`0xc00bd000`** — **CPU exception handler / register dumper** (NOT
  related to descriptors, despite earlier misreading). The printf
  labels at `0xc00e83fd`-area resolve to `B18=0x%x B19=0x%x`,
  `NTSR=0x%x`, `ITSR=0x%x`, `IRP=0x%x`, `SSR=0x%x`, `AMR=0x%x`,
  `RILC=0x%x`, `ILC=0x%x`, `Exception at 0x%x` — i.e. CPU control
  registers, not parameter fields. A11 in this function points to a
  saved-CPU-context buffer, not a runtime entry struct.
  **Retraction:** the earlier claim that "the runtime entry struct is
  0x48 bytes" was unfounded — it was misreading of this exception
  handler's stride. We have no confirmed evidence of the runtime
  entry struct's true size or layout.

### Findings from forward tracing of walk_descriptor

* The `BNOP c00bb6ec` at `c00bb68c` is **not** a fallback — `c00bb860`
  (its eventual destination) is the function epilogue (`ADDK 32,B15`
  + `pop_rts`). So this is just an "early return" path when
  `walked_count < declared_count`.
* `c00bb600` has 7 known callers, each passing different `arg2` values
  (`1`, `0`, `-1`, …). So it's a **multipurpose descriptor iterator**,
  not specifically the UI walker.
  - `c00abb2c` caller: `arg2 = 1`
  - `c00abcf8` caller: `arg2 = 0`
  - `c00aec20` caller: `arg2 = -1`
  - `c00bb8c0` / `c00bb910` recursive callers
* The UI rendering uses a different code path that operates on
  pre-parsed runtime state structs (the 0x48-byte form from the
  debug-print function), not the on-disk descriptor directly.

### Strongest unverified hypothesis after this session

`effectTypeImageInfo +0x18` (we set `28` from LineSel; stock 3-param
effects use `32`):

| Effect | +0x18 | +0x1C | knob count |
|---|---|---|---|
| Exciter | 32 | 17 | 3 |
| OptComp | 32 | 17 | 3 |
| ZNR | 46 | 29 | 3 (1 + 2 — switch + knobs) |
| AIR | 21 | 23 | 6 paginated |
| **TapeHack (us)** | **28** | **17** | 3 |

We never specifically tested changing **just** `+0x18` from 28 to 32
in isolation. Cheapest next hardware test.

### Suggested next steps if resumed

1. **Flash test:** set `imageInfo +0x18 = 32`, keep `+0x1C = 17`.
   One-line change in `_build_image_info`. Single most-likely outcome
   given the data we have.
2. If that fails, the UI rendering code path operates on pre-parsed
   0x48-byte runtime structs. Find the function that CONVERTS on-disk
   SonicStomp entries (0x30 each) to the runtime 0x48-byte form, and
   look at what it does with our 3rd entry.
3. The 0x48-byte struct layout (from the c00bd000 debug printer):
   - word 0..2 = name (12 bytes)
   - word 3 = max_val
   - word 4 = default_val
   - word 6 = ??? (offset +0x18; printed)
   - word 7 = func_ptr (+0x1C)
   - word 10 = ??? (+0x28)
   - word 11 = pedal_flags (+0x2C)
   - word 12..17 = ??? (+0x30..+0x44 — TWO MORE WORDS beyond on-disk
     SonicStomp's 0x30-byte size. These are firmware-only fields added
     during the parse.)
4. The 0x48-vs-0x30 size mismatch implies the firmware allocates
   memory and copies fields. If the parse only copies the on-disk
   entry's 0x30 bytes, the extra 0x18 bytes of runtime state must be
   initialised from elsewhere (effectTypeImageInfo? a fixed pattern?).
   That extra state is probably what's hashed/checked for the
   visible-knob count.

## Working artifacts produced during the investigation

* `dist/AirCtl.ZDL` — historical minimally-modified stock AIR diagnostic, no
  longer shipped in the clean release `dist/`
  (renamed, fxid bumped). Confirms 6-param render works on hardware.
* `dist/TapeHKEx.ZDL` — historical minimally-modified stock
  Exciter (renamed, fxid bumped). Confirms 3-param render works.
* [src/airwindows/tapehack/build_via_template.py](../src/airwindows/tapehack/build_via_template.py)
  — splices a compiled `.audio` section into a stock 3+ param ZDL as
  a template. Output runs but knob ranges follow the template's edit
  handlers, not the user's intent — needs handler synthesis to be
  truly drop-in.


  Attemted fix: Verified — all freshly built dist plugins now have 20.0f at the right offset; template-spliced ones (AirCtl/HELLO/TapeHKEx) keep their stock values.

Let me record this as a feedback memory since it's a non-obvious linker invariant that's easy to break:
