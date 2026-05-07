# ZDL runtime ABI — what a Zoom DSP plugin looks like, end to end

Written before our first ground-up port, so we go in with eyes open
instead of mystery-flashing. Everything below is derived from:

* `ofd_zdl.txt` — `ofd6x` dump of `MS-70CDR_EXCITER.ZDL` (full symbol
  table, relocation table, section addresses).
* `working_zdls/MS-70CDR_EXCITER.ZDL` — the on-disk bytes, cross-checked
  against the relocations.
* `working_zdls/MS-70CDR_LINESEL.ZDL` — second data point.
* `zoom-fx-modding-ref/library/CH_2.md` — conversational disassembly
  of LineSel; provides DSP-loop semantics.
* `ZoomPedalFun-main/MS70CDR/DerivedData/2.10/checkme.py` — independent
  RE of the SonicStomp entry layout (corroborates `OnOffblockSize=0x30`).

Items still inferred (not directly observed) are flagged **[ASSUMPTION]**.

---

## 1. Toolchain target

| Property         | Value                                  |
|------------------|----------------------------------------|
| ISA              | TI C6740 (`Tag_ISA = 8`)               |
| ABI              | EABI (`Tag_ABI = 2`)                   |
| Endianness       | Little                                 |
| `long` width     | 32-bit (`Tag_Long_Precision_Bits = 2`) |
| `wchar_t`        | 16-bit                                 |
| Output           | ELF32 shared object (`ET_DYN`)         |
| Compiler         | TI C6000 v8.3.x (CCS 8.x)              |
| Linker version   | 7.3.7 (per the factory ELFs)           |

The ELF program headers Exciter ships with:

```
PH0  PT_LOAD  vaddr 0x00000000  filesz 0x6c0  flags r-x   (.text + .audio)
PH1  PT_LOAD  vaddr 0x80000000  filesz 0x458  flags r--   (.const)
PH2  PT_LOAD  vaddr 0x80000458  filesz 0x18   flags rw-   (.fardata)
PH3  PT_DYNAMIC                 size  0xa8                 (.dynamic)
```

A linker command file targeting this layout is the foundation of any
ground-up port. `.text` and `.const` are read-only at runtime; only
`.fardata` is writable, and it's used for *static* knob bitmaps and the
like — not for per-instance state.

---

## 2. The exported symbol contract

The host firmware finds your DLL's entrypoints **by name** in the
`.dynsym` table. A complete plugin must export exactly:

| Symbol                          | Kind     | Where it lives | Purpose                                         |
|---------------------------------|----------|----------------|-------------------------------------------------|
| `Dll_<Name>`                    | function | `.text`        | DLL load entry. Returns/registers the structs.  |
| `Fx_FLT_<Name>`                 | function | `.text`        | Per-buffer audio loop (the DSP).                |
| `Fx_FLT_<Name>_init`            | function | `.text`        | One-shot per-instance init.                     |
| `Fx_FLT_<Name>_onf`             | function | `.text`        | On/Off (bypass) handler.                        |
| `Fx_FLT_<Name>_<param>_edit`    | function | `.text`        | One per knob; runs when the user turns it.      |
| `picEffectType_<Name>`          | object   | `.const`       | RLE-compressed 128×40 1-bpp picture.            |
| `effectTypeImageInfo`           | object   | `.const`       | UI layout (image dims + per-knob xy + bitmap).  |
| `_infoEffectTypeKnob_A_2`       | object   | `.fardata`     | Knob bitmap descriptor (24 bytes; can share).   |
| `SonicStomp`                    | object   | `.const`       | **The** plugin descriptor — table of pointers.  |
| `_Fx_FLT_<Name>_Coe`            | object   | `.const`       | Coefficient/lookup table (effect-specific).     |

`<Name>` is a free identifier (PascalCase per Zoom's convention).
`<param>` is the lowerCamelCase knob name (e.g. `loContour`, `outlv`).

---

## 3. `SonicStomp` — the plugin descriptor

This is the centerpiece. It's a 240-byte struct in `.const`, structured
as five 48-byte (`0x30`) entries:

```
SonicStomp                              ┐
  Entry[0] OnOff   bytes   0..47       │  240 bytes
  Entry[1] <Name>  bytes  48..95        │
  Entry[2] knob1   bytes  96..143       │
  Entry[3] knob2   bytes 144..191       │
  Entry[4] knob3   bytes 192..239       ┘
```

Each entry has the same shape, with field meaning depending on entry kind:

```
struct SonicStompEntry {                  // 48 bytes
    char     name[12];        // +0   visible label, NUL-padded
    uint32_t max;             // +12  max integer value (1 for OnOff, 100/150 for knobs)
    uint32_t default_value;   // +16  default integer
    uint32_t reserved_a[2];   // +20
    uint32_t handler;         // +28  primary function pointer (see below)
    uint32_t extra;           // +32  audio loop ptr (DLL entry only); else 0
    uint32_t reserved_b[2];   // +36
    uint32_t pedal_flag;      // +44  non-zero → controllable by expression pedal
                              //      (per ZoomPedalFun's `checkme.py`)
};
```

**Per-entry meaning of `handler`:**

| Entry          | handler points to              | extra (+32)              |
|----------------|--------------------------------|--------------------------|
| `OnOff`        | `Fx_FLT_<Name>_onf`            | 0                        |
| `<Name>` (DLL) | `Fx_FLT_<Name>_init`           | `Fx_FLT_<Name>` (audio)  |
| knob entries   | `Fx_FLT_<Name>_<param>_edit`   | 0                        |

The Exciter values, observed on disk:

| Entry   | name     | max  | default | handler         | extra            |
|---------|----------|------|---------|-----------------|------------------|
| 0       | "OnOff"  | 1    | 0       | onf             | 0                |
| 1       | "Exciter"| 0xFFFFFFFF | special | init        | audio loop       |
| 2       | "Bass"   | 100  | 0       | loContour_edit  | 0                |
| 3       | "Trebl"  | 100  | 0       | process_edit    | 0                |
| 4       | "Level"  | 150  | 100     | outlv_edit      | 0                |

`max = 0xFFFFFFFF` on the DLL self-entry signals "this isn't a knob, it's
the plugin itself" — the firmware skips it during knob iteration.

The five-entry shape implies a hard cap of **3 user knobs** for this
SonicStomp variant. Effects with more knobs presumably use a longer
SonicStomp; we'll figure that out when we hit it.

---

## 4. `effectTypeImageInfo` — UI layout (212 bytes)

A second `.const` struct, parallel to SonicStomp, that tells the
firmware where to *paint* things:

```
offset  type    field
------  ------  -----
   0    u32     0
   4    u32     1
   8    u32     0
  12    u32     image width   (= 128)
  16    u32     image height  (= 64)
  20    u32*    picEffectType_<Name>  ← reloc
  24    u32     ?  (Exciter: 32)
  28    u32     ?  (Exciter: 17)
  32    u32     knob_count    (= 3)
  -- per-knob block (16 bytes), repeats knob_count times --
  +0    u32     knob_id
  +4    u32     x  (top-left, in pixels)
  +8    u32     y
  +12   u32*    -> _infoEffectTypeKnob_A_2  ← reloc
  ...
  remainder zero-padded (room for ~8 knobs total)
```

Notes:
* The picture is *not* embedded — it's a pointer to a separate `.const`
  blob. Editing artwork = editing `picEffectType_<Name>` and leaving
  this struct alone.
* The knob_id is what gets passed to the runtime "get knob value"
  callback (see §5).
* All three knobs in Exciter point to the *same* `_infoEffectTypeKnob_A_2`
  bitmap — knob shapes are shared.
* CH_1.md mentions image dimensions are 128×64 in `effectTypeImageInfo`,
  while only the *top* 128×40 is the FX picture; the lower band is for
  knobs and labels painted by the firmware. So 128×64 is the
  paintable area; 128×40 is what you draw.

`_infoEffectTypeKnob_A_2` itself (24 bytes, in `.fardata`) is a tiny
descriptor of the knob bitmap shape — width, height, inner-circle dims.
Documented in CH_1.md.

---

## 5. The C6000 calling convention (what the firmware passes)

TI C6000 EABI scalar conventions:

| Register | Role                                      |
|----------|-------------------------------------------|
| `A4`     | arg 0 / return value                      |
| `B4`     | arg 1                                     |
| `A6`     | arg 2                                     |
| `B6`     | arg 3                                     |
| `B3`     | return address                            |
| `B15`    | stack pointer                             |
| `A14`/`B14` | preserved (data-page pointer)         |

All handlers seen in CH_2.md follow stock CCS prologue/epilogue
(save B3, allocate stack via B15, restore on exit).

### 5.1 Knob/OnOff `_edit` and `_onf` handlers

From CH_2.md's walkthrough of LineSel, all "edit" handlers and `onf`
share a shape:

```c
void Fx_FLT_<Name>_<param>_edit(SonicStompState *state, /* B4: arg1 */ ...);
```

Inside the handler: it reads `A6[?]` (= some host-state pointer), then
calls a host callback (also reached via that pointer) to fetch the
current integer knob value. The callback's **2nd argument is the
knob_id** — this is why CH_2.md notes "Efx gives 2, and Out gives 3":
each handler hardcodes the knob ID it represents, matching what
`effectTypeImageInfo` advertised.

The handler converts the integer (0..max) into a normalized float
0..1.0 and stores it at a fixed location for the audio loop to read.
LineSel uses a bias of `1.0 / max` (= `1.0/150` for OUT_L); Exciter
uses similar normalizers in its `_Coe` table.

**[ASSUMPTION]** The SonicStomp itself (or a parallel runtime state)
is what's passed in `A6`. CH_2.md describes the indirection generically
("a function pointer at offset 31 words in the 1st argument struct")
without naming the struct — but since SonicStomp is the only struct
the DLL exports that has a callback-shaped offset like this, that's
the most likely candidate. Verify on first ground-up build.

### 5.2 The audio loop `Fx_FLT_<Name>`

```c
void Fx_FLT_<Name>(BufferState *bs);
```

Where `BufferState` (called via `A4`/`A6`) holds:

* `Effect L` / `Effect R` buffer pointers — wet path.
* `Guitar L` / `Guitar R` buffer pointers — dry path.
* `Output L` / `Output R` buffer pointers — accumulator.
* Block size (sample count per channel).

CH_2.md's LineSel walkthrough confirms the buffer-pointer-loading idiom
(`A7[0]..A7[7]` → `A6[0]`) and the stride. **Three** logical buffer
pairs (Effect/Guitar/Output) — this is the LineSel "trick book" that
gives effects access to both the wet and dry signal independently.

#### Sample format

* **`float32`, IEEE-754, mono per channel.** CH_2.md is explicit:
  binary `01111111 << 23 = 0x3F800000` is "1.0 in float", and the
  effect coefficients (`__k0`..`__k6`) are floats throughout.
* Channel layout in memory: blocks of 8 samples per channel, then
  the other channel — `LLLLLLLL RRRRRRRR LLLLLLLL RRRRRRRR ...`.
  This is what enables the compiler to unroll the inner loop 8× cleanly.

#### Output is *added*, not assigned

Critical: the audio loop **adds** its contribution to `Output`, never
overwrites. Downstream effects in the chain still receive the input
signal independently — that's why a reverb's tail survives a switch-off
later in the chain. From CH_2.md:

> "Notice addition to output buffer, not overriding. To me this seems
> to be made to preserve trails of any effects that have them."

So a clean pass-through is `Output += Effect` (when on) or `Output += 0`
(when off). A new effect like gain is `Output += Effect * gain`.

#### Sample rate

* **44.1 kHz**, 24-bit codec (MS-70CDR datasheet). DSP samples are
  float32 internally regardless of codec width.

#### Block size

* **[ASSUMPTION]** A multiple of 8 samples per channel; exact value
  not directly observed. Typical embedded DSP block sizes are 32 or
  64 samples. We'll instrument this on the first ground-up plugin
  by writing a known-period sine-from-counter and measuring how it
  steps across calls.

### 5.3 Init `Fx_FLT_<Name>_init`

CH_2.md observed for LineSel: init calls `_onf`, `_edit_efx`, `_edit_out`
in sequence, all with a fixed magic state-pointer
(`0x80000378` for LineSel). That suggests init is called *once* with
some host-provided state, and its job is to push initial values for
each parameter into the runtime by invoking the per-param handlers.

For Exciter, init at `.text+0x5c0` (per `Fx_FLT_Exciter_init` symbol)
should follow the same pattern — invoke onf, then each edit handler.

### 5.4 DLL entry `Dll_<Name>`

The ELF entry point. Relocations show it loads pointers to both
`SonicStomp` and `effectTypeImageInfo`, which means it returns/registers
the pair as a "this is who I am" handshake. **[ASSUMPTION]** signature:

```c
struct DllInfo { SonicStomp *desc; effectTypeImageInfo *ui; };
DllInfo* Dll_<Name>(void);
```

To verify, disassemble `Dll_Exciter` at `.text+0x660`. (Eight
instructions per the ofd; should be readable by hand.)

---

## 6. Memory map and constraints

| Region        | Address                | Notes                                       |
|---------------|------------------------|---------------------------------------------|
| `.text`       | `0x00000000` upward    | Code. Read-only at runtime.                 |
| `.const`      | `0x80000000` upward    | Read-only data (SonicStomp, picture, coefficients). |
| `.fardata`    | `0x80000458` upward    | Writable; small (LineSel: 24 bytes total).  |
| Stack         | `B15` provided by host | Don't overflow — no MMU, no guard page.     |

* **No malloc.** All state is statically allocated (globals in
  `.fardata`, locals on stack).
* **No FPU exceptions** worth catching — the C6740 has hardware float;
  treat NaN/Inf the same as Airwindows desktop builds do.
* **No threading.** Audio loop is called from a single audio task; init
  and edit handlers from a (presumably) higher-priority UI task. Don't
  assume atomicity; **[ASSUMPTION]** simple word writes are the de
  facto sync primitive.

---

## 7. The LineSel "trick book" (relevant for any port)

LineSel teaches the cleanest mental model for the host's signal flow:

1. The audio function gets three buffer pairs: **Effect (wet)**,
   **Guitar (dry)**, **Output (accumulator)**.
2. **Effect** is the upstream signal *as modified so far* by previous
   effects in the chain.
3. **Guitar** is always the original raw input.
4. **Output** accumulates whatever each effect adds; final
   speaker-bound signal is `Output` after the last effect runs.
5. Most factory effects compute `wet_out = process(Effect)`, write
   that back into `Effect` (so the next effect sees it), and don't
   touch `Output` (so trails decay cleanly when this effect is bypassed).

This means a port like Airwindows `Console` channel — which is itself
a clean sum stage — maps directly onto reading `Effect`, summing, and
writing back `Effect` (or directly into `Output` if it's the last
effect we care about). Most Airwindows kernels are sample-by-sample
and don't care about the L/R interleave subtlety.

---

## 8. Summary checklist for our first ground-up plugin

To produce a loadable ELF, we need:

- [ ] CCS 8.x project, generic C674x, C6000 v8.3.x compiler, ABIv2.
- [ ] Linker command file with three segments at the addresses in §1.
- [ ] One C/asm source file exporting the §2 symbols, with `Dll_<Name>`
      as the ELF entry point.
- [ ] A correctly-shaped `SonicStomp` (§3) and `effectTypeImageInfo` (§4).
- [ ] `Fx_FLT_<Name>` operating on float32 in/out, *adding* to Output
      (§5.2).
- [ ] `_init`, `_onf`, and per-param `_edit` handlers (§5.1).
- [ ] A `picEffectType_<Name>` blob — can stub with all-zeros to start;
      icon will look blank but the unit will boot.
- [ ] A picture pointer + knob layout in `effectTypeImageInfo`.

When the linked `.out` is small (under a few KB) and exports exactly
the §2 symbol set, our existing `build/zdl.py` can wrap it into a ZDL
unchanged — the SIZE field is recomputed from `len(elf)` on save.

---

## 9. Open questions to settle empirically

* Exact `BufferState` field offsets (only the *count* of pointers is
  known from CH_2.md).
* Block size in samples.
* Whether `init` runs once at firmware boot or every time the user
  selects the effect in a patch.
* Meaning of the four "unknown" SonicStomp-entry words at +20..+27 and
  +36..+43.
* How the `pedal_flag` at +44 changes runtime behavior (edit handler
  invocation rate? a separate pedal-callback?).
* The `A6[31]` host callback: signature, what it returns for OnOff
  (which has only values 0/1) vs continuous knobs.

These are the things to pin down on the first GAIN flash. Each gets one
small experiment on the unit.
