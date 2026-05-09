# Build pipeline — Airwindows → Zoom MS-70CDR (ZDL)

This document describes the full reproducible workflow for turning a piece
of DSP (eventually: an Airwindows plugin) into a `.ZDL` file that the Zoom
MS-70CDR will load as a stock-feeling effect.

The pipeline is intentionally split into two halves:

1. **Container layer** (this directory). Pure Python, no toolchain needed.
   Reads/writes the ZDL header (NULL + SIZE + INFO blocks) and patches
   labels inside the embedded ELF in place.
2. **DSP layer** (later). Texas Instruments C6000 toolchain produces a
   linked ELF shared object (`.out`); the container layer wraps it.

`hello/` is the proof that the container layer works end-to-end. Real
ports replace the ELF; everything else stays.

---

## Repository layout

```
airwindowsZoom_v2/
├── README.md                  # top-level overview for new contributors
├── build/
│   ├── ABI.md                 # authoritative runtime ABI write-up
│   ├── linker.py              # static linker (.obj → .ZDL)
│   ├── zdl.py                 # ZDL container parser/writer + label patcher
│   ├── linesel_handlers.bin   # onf + knob1 + knob2 + RTS helpers (LineSel)
│   ├── air_knob3_edit.bin     # knob3 edit handler (AIR mix_edit)
│   ├── divf_rts.bin           # __c6xabi_divf RTS code
│   └── README.md              # this file
├── src/
│   └── airwindows/
│       ├── hello/             # minimal pass-through, validates flash/boot
│       ├── gain/              # 1-knob volume trim
│       ├── purestdrive/       # Airwindows PurestDrive (1 knob)
│       ├── tapehack/          # Airwindows TapeHack (3 knobs)
│       └── bitcrush/          # bit/SR crusher (1 knob)
├── docs/CONTRIBUTING.md       # open questions + workflow rules
├── working_zdls/              # ~830 stock ZDLs (templates / references)
├── firmware/                  # MS-70CDR firmware blobs (boot/Main/FS/Preset)
├── airwindows-ref/            # Airwindows source (reference; future ports)
├── zoom-fx-modding-ref/       # third-party RE notes, picture en/decoder
├── ZoomPedalFun-main/         # MS-70CDR-specific reverse-engineering
└── Zoom-Firmware-Editor-master/  # Java tool: bundles ZDLs into firmware
```

## ZDL container format (recap)

```
offset  bytes  field
------  -----  -----
   0      4    NULL prefix      (00 00 00 00)
   4      4    "SIZE"
   8      4    SIZE payload size  (always 8)
  12      4    header size after this field  (56 typical)
  16      4    ELF size in bytes
  20      4    "INFO"
  24      4    INFO payload size  (always 48)
  28     32    version string  ("ZOOM EFFECT DLL SYSTEM VER 1.00\0")
  60      8    type/sort byte fields  (real_type, unknown1, knob_type,
              unknown2, sort_index, sort_sub, bass_flags, sort_fx_type)
  68      8    fx_version  (e.g. "1.01\0\0\0\0")
  76    ...    ELF (TI C6740, EABI, little-endian, shared object)
```

All values little-endian. Source: `zoom-fx-modding-ref/library/CH_4.md`.

`real_type` controls the FX category icon and routing. `sort_index` ≤240
collides with stock effects; **use 240+ for new effects** so they show up
as additional menu entries instead of replacing originals.

## How a ZDL is structured *internally* (the ELF side)

A factory ZDL's ELF exports a fixed set of symbols, addressed by name in
`.dynsym`. The Exciter we have in `ofd_zdl.txt` is canonical:

| Symbol                              | Role                                        |
|-------------------------------------|---------------------------------------------|
| `Dll_<Name>`                        | DLL entry point (the `e_entry` of the ELF). |
| `Fx_FLT_<Name>`                     | Audio-loop function (called per buffer).    |
| `Fx_FLT_<Name>_init`                | One-shot init.                              |
| `Fx_FLT_<Name>_onf`                 | On/Off handler (effect bypass logic).       |
| `Fx_FLT_<Name>_<param>_edit`        | One per knob — runs when the user turns it. |
| `picEffectType_<Name>`              | RLE-compressed 128×40 pixel art (`.const`). |
| `effectTypeImageInfo`               | Layout struct: image size + knob positions. |
| `_infoEffectTypeKnob_A_2`           | Knob bitmap descriptor (`.fardata`).        |
| `_Fx_FLT_<Name>_Coe`                | Effect coefficients table.                  |
| `SonicStomp`                        | Container struct that ties the above together. |

This naming convention is a *contract* with the firmware's effect loader.
A new plugin must export a matching set; you can rename `<Name>` freely.

### Parameters

The pedal's runtime calls the per-knob `_edit` handlers with a knob ID
(integer) and reads back a float. The conventional return is the knob's
0..1.0 normalized value, sometimes pre-scaled. See
`zoom-fx-modding-ref/library/CH_2.md` § "Reading state, parameters" for a
disassembled walkthrough of LineSel's three handlers.

### DSP processing

`Fx_FLT_<Name>` is the audio loop. It receives a struct holding pointers
to four interleaved buffers — Effect L/R (the wet path) and Guitar L/R
(the dry path) — plus a sample count. The compiler unrolls the inner
loop 8× by default (8-sample stride per channel).

Critically: **output is added, not assigned.** Each effect modifies a
shared output buffer; downstream effects still see input. This is what
lets reverb/delay tails survive a switch-off later in the chain. See
`CH_2.md` § "Adding Effect signal to the final output".

### UI hooks (the picture + knob layout)

The "UI" is two things:

1. A 128×40 1-bpp picture in `.const`, RLE-compressed. Editable as ASCII
   art via `zoom-fx-modding-ref/diy/decode_picture.py` /
   `encode_picture.py`. Knob shapes are *not* baked into the picture —
   the firmware paints them on top using the `_infoEffectTypeKnob_A_2`
   bitmap. That's why most effect pictures look like they have round
   holes where the knobs are.
2. An `effectTypeImageInfo` struct that lists `(knob_id, x, y, knob_ptr)`
   tuples. Edit the `(x, y)` to move the knob; bump `knob_id` to add or
   remove knobs.

Layout is documented in `zoom-fx-modding-ref/library/CH_1.md`
§ "Optional: knob positions".

---

## Toolchain

| Component                         | Purpose                       | Notes |
|-----------------------------------|-------------------------------|-------|
| Python ≥3.10                      | Container packaging (this repo). | No external deps. |
| **TI Code Composer Studio (CCS)** | Builds the ELF for C674x.     | Use CCS 8.x with the C6000 8.3.x compiler. The pedals use ABI v2, ISA C6740, EABI, 32-bit `long`. |
| **TI `dis6x`**                    | Disassembles `.obj` / `.out`. | Ships with CCS. Used for analysis and verifying compiled output. |
| **Zoom Firmware Editor**          | Bundles `.ZDL`s into a flashable firmware blob (`.bin`). | https://github.com/Barsik-Barbosik/Zoom-Firmware-Editor. Java; included in `Zoom-Firmware-Editor-master/`. |
| Optional: LunarIPS                | Distribute patches without redistributing Zoom IP. | |

### Compiler flags that match the factory ELFs

Verified against `ofd_zdl.txt` (Exciter):

* Generic C674x device, `-mv6740` ISA tag.
* EABI (`Tag_ABI = 2`).
* `Tag_Long_Precision_Bits = 2` → 32-bit `long`.
* Optimizations on; the originals favor speed (instruction width) over size.
* Output: shared object (`.out`). The *file extension* `.zdl.code` Zoom
  uses is just convention.

The CCS project type is **"Empty Assembly-only project"** if you start
from disassembled `.asm`, or a normal C/C++ project if you write in C.
See `zoom-fx-modding-ref/library/CH_3.md` for click-by-click setup.

### Hardware

* MS-70CDR (target).
* USB Mini cable with data lines (power-only cables won't enumerate the
  pedal in firmware-update mode — common gotcha).

---

## Flashing / loading workflow

The pedal accepts a single firmware image, not loose ZDLs. Workflow:

1. `python3 build_all.py hello` → `dist/HELLO.ZDL`.
2. Open `Zoom-Firmware-Editor-master/ZoomFirmwareEditor.jar`.
3. Load the official MS-70CDR firmware (the `.bin` Zoom distributes).
   Backup blobs are in [firmware/](../firmware/) (`boot.bin`, `Main.bin`,
   `FS.bin`, `Preset.bin`).
4. **Add** `HELLO.ZDL` to the FX list (do not replace `LINESEL.ZDL` —
   `sort_index = 250` lets HELLO sit alongside the originals).
5. Save the modified firmware to a new `.bin`.
6. On the pedal: hold **UP + DOWN** while connecting USB → unit boots in
   firmware-update mode.
7. Run Zoom's official updater (or the editor's flash tool) and point it
   at the modified `.bin`.
8. Power-cycle when done. Scroll past the factory FX — `HELLO` should
   appear as a new entry.

> **Safety:** keep the unmodified Zoom firmware nearby. If a flash
> bricks the unit, you re-enter UP+DOWN mode and re-flash the original.
> The bootloader (`firmware/boot.bin`) is separate from `Main.bin` and is
> what makes recovery possible — do not touch it unless you know what
> you're doing.

---

## Workflow for a new Airwindows port

See the recipe in the [top-level README](../README.md#adding-a-new-effect--a-5-step-recipe).
In short:

1. Pick an Airwindows plugin from [airwindows-ref/](../airwindows-ref/).
2. Copy [src/airwindows/gain/](../src/airwindows/gain/) as a
   skeleton; rename and edit `<name>.c`, `manifest.json`, and `build.py`.
3. Add an entry to [build_all.py](../build_all.py).
4. `python3 build_all.py <name>` → ZDL drops into `dist/`.
5. Flash via Zoom Effect Manager (or the bundled Firmware Editor) and
   audition. Start with `audio_nop: true` to confirm the build is
   structurally OK before exercising the DSP.

`build/zdl.py` is the only piece of the container layer; it is small on
purpose. As we hit edge cases (BCAB/CABI sections in cab effects, larger
ELFs, multi-page pictures), they get added there.

---

## Known unknowns

* `INFO.unknown1` / `INFO.unknown2` semantics are not pinned down. We
  copy them from the LineSel template and they work; varying them is
  unexplored.
* The `SonicStomp` struct layout is empirical — Exciter's
  `ofd_zdl.txt` shows it sits in `.const` at +0x250 but the field
  definitions aren't documented yet. For now we don't touch it.
* Picture-encoder corner cases on long horizontal runs of identical
  pixels — covered in `zoom-fx-modding-ref/howto/RTFM.md`.
