# ZDL runtime ABI — what a Zoom DSP plugin looks like, end to end

Written before our first ground-up port, so we go in with eyes open
instead of mystery-flashing. Everything below is derived from:

* `ofd_zdl.txt` — `ofd6x` dump of `MS-70CDR_EXCITER.ZDL` (full symbol
  table, relocation table, section addresses).
* `stock_zdls/MS-70CDR_EXCITER.ZDL` — the on-disk bytes, cross-checked
  against the relocations.
* `stock_zdls/MS-70CDR_LINESEL.ZDL` — second data point.
* **The v1 project at `~/coding/airwindowsZoom/`** — most importantly
  `ZDL_Findings.md` (descriptor format reverse-engineered from all 128
  stock MS-70CDR ZDLs) and `build/link_zdl.py` (the linker that
  successfully produced `TOTAPE9_AUDIO.ZDL`, which booted on real
  hardware and was selectable in the FX menu). Every load-bearing
  constant in v1's linker has a comment explaining the experiment that
  pinned it down. Items below marked **[v1-empirical]** were verified
  on hardware via bisection — change them only with proof.
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

This is the centerpiece. It's a variable-length array in `.const` of
48-byte (`0x30`) entries. The **last entry is marked by setting bit
`0x04` in `pedal_flags` at offset `+0x2C`** — the firmware walks entries
from the table start until it sees this sentinel. There is **no fixed
entry count**: stock LO-FI Dly has 11 entries (OnOff + name + 9 knobs);
HELLO/LineSel have 4. [v1-empirical, verified across all 128 stock ZDLs]

```
SonicStomp ::=  [OnOff entry]
                [<Name> entry]
                [knob entry]+        // one per parameter
                                     // last knob has pedal_flags & 0x04
```

Each entry layout (corrected against v1's full survey of 128 ZDLs):

```c
struct SonicStompEntry {                  // 48 bytes
    char     name[12];        // +0x00  visible label, NUL-padded
                              //        up to 12 chars on the name entry,
                              //        up to 8 on parameter entries
    uint32_t max_val;         // +0x0C  max integer value
                              //        (0xFFFFFFFF on the name entry)
    uint32_t default_val;     // +0x10  default integer
    uint32_t pedal_max;       // +0x14  same as max_val if pedal-assignable,
                              //        0 otherwise
    uint32_t reserved_a;      // +0x18  usually 0; non-zero in some
                              //        delay/pitch effects (sub-range?)
    uint32_t func_ptr;        // +0x1C  PRIMARY handler (relocated, ABS32):
                              //          OnOff entry  → onf
                              //          name entry   → init
                              //          knob entry   → <param>_edit
    uint32_t audio_ptr;       // +0x20  audio loop ptr (relocated, ABS32);
                              //        non-zero ONLY on the name entry,
                              //        0 elsewhere
    uint32_t getstr_ptr;      // +0x24  optional value-to-string formatter
                              //        for display; 0 if none
    uint32_t reserved_b;      // +0x28  usually 0
    uint32_t pedal_flags;     // +0x2C  bitmask, see below
};
```

`pedal_flags` bitmask (`+0x2C`) — cross-checked against the stock corpus:

| Mask   | Bit | Meaning                                                   |
|--------|-----|-----------------------------------------------------------|
| `0x04` | 2   | **End-of-table sentinel** — last parameter entry          |
| `0x10` | 4   | Pedal/expression-assignable parameter marker              |
| `0x28` | 3+5 | Tempo-synced (both bits required)                         |

Common observed values: `0x00` (regular knob), `0x04` (last-param,
not pedal), `0x10` (pedal/expression assignable), `0x14` (last +
pedal/expression assignable), `0x28` (tempo), `0x38` (tempo +
pedal/expression assignable).

Important correction: `0x10` is not the missing "make this effect stereo"
switch. It appears on mono stock effects such as `CHORUS`, `DELAY`, and many
amp/drive parameters whenever those parameters are expression-assignable, and
stock effects with explicit Mono/Stereo mode parameters use ordinary descriptor
entries plus `GetString_MonoStereo` display helpers. Treat stereo routing as
still unmapped.

**The Exciter values, observed on disk** (note +0x14 = 1 on the name
entry — that's `pedal_max = 1`, common but its purpose is unclear):

| Entry   | name     | max        | default | pedal_max | func_ptr        | audio_ptr | flags   |
|---------|----------|------------|---------|-----------|-----------------|-----------|---------|
| 0       | "OnOff"  | 1          | 0       | 0         | onf             | 0         | 0x00    |
| 1       | "Exciter"| 0xFFFFFFFF | 0       | 1         | init            | audio     | 0x00    |
| 2       | "Bass"   | 100        | 0       | 0         | loContour_edit  | 0         | 0x00    |
| 3       | "Trebl"  | 100        | 0       | 0         | process_edit    | 0         | 0x00    |
| 4       | "Level"  | 150        | 100     | 150       | outlv_edit      | 0         | 0x14    |

**On disk, `func_ptr` and `audio_ptr` are zero** — the dynamic linker
resolves them at load time from `.rela.dyn` ABS32 entries. Same for the
descriptor symbol's address everywhere it's referenced (e.g. inside
`Dll_<Name>`).

---

### 3.1 Pagination — how >3 knobs work [hardware-confirmed]

`effectTypeImageInfo` carries the total user-parameter count, but only
the first three coordinate blocks are meaningful. The firmware paginates
edit mode by walking the descriptor table from the name entry until the
`pedal_flags & 0x04` sentinel, overlaying entries onto 3 fixed visible
slots three-at-a-time.

The earlier "nknobs=9 breaks paging" reading was incomplete: the real
bug was the DLL entry stub still declaring NoiseGate's descriptor count
of `4`. Once `Dll_<Name>` declares `2 + len(params)`, hardware renders
and edits 3, 5, 7, and 9 parameter builds.

## 4. `effectTypeImageInfo` — UI layout (212 bytes)

A second `.const` struct, parallel to SonicStomp, that tells the
firmware where to *paint* things:

```
offset  type    field
------  ------  -----
0x00    u32     0
0x04    u32     1
0x08    u32     0
0x0C    u32     image width   (= 128)
0x10    u32     image height  (= 64)
0x14    u32*    picEffectType_<Name>  ← ABS32 reloc
0x18    u32     unknown (0x1C or 0x20)
0x1C    u32     unknown (0x18 or 0x19)
0x20    u32     user parameter count (3 for single-page, 4-9 for paginated)
  -- per-knob block (16 bytes), first 3 visible slots populated --
  +0    u32     knob_id  (1-based parameter index;
                          1 = OnOff, 2 = first knob, …)
  +4    u32     x  (top-left, in pixels)
  +8    u32     y
  +12   u32*    -> _infoEffectTypeKnob_A_2  ← ABS32 reloc
  ...
  zero-padded to exactly 212 bytes total       [v1-empirical]
```

Notes:
* **The struct must be padded to exactly 212 bytes.** Smaller breaks
  paging on hardware. With 3 knob entries the populated portion is
  `0x20 + 4 + 3·16 = 84` bytes; the rest is zeros. [v1-empirical]
* The picture is *not* embedded — it's a pointer to a separate `.const`
  blob. Editing artwork = editing `picEffectType_<Name>` and leaving
  this struct alone.
* The knob_id is what gets passed to the runtime "get knob value"
  callback (see §5).
* All three knobs in Exciter point to the *same* `_infoEffectTypeKnob_A_2`
  bitmap — knob shapes are shared.

`_infoEffectTypeKnob_A_2` is a 24-byte struct in `.fardata`,
**always exactly `{20, 15, 11, 0, 2, 0}` as six little-endian u32s**.
[v1-empirical: field4=5 was tried once and froze the unit at FX-select
time; field4=2 ships in all 128 stock ZDLs.]

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

### 5.3.a Buffer-state struct field map [v1-confirmed]

From `zoom-fx-modding-ref/diy/{rainsel,rtfm,div0}.asm` (three independent
from-scratch effects, all with consistent A4-field accesses):

```
A4 = ctx (state pointer; arg 0)
  ctx[1]   →  parameters table (an array of float values, see §5.4)
  ctx[4]   →  Dry buffer    (float*, raw guitar-input signal)
  ctx[5]   →  Fx  buffer    (float*, signal modified by upstream chain)
  ctx[6]   →  Output buffer (float*, accumulator — ADD into this)
  ctx[11]  →  "magic dest"  (must shuttle bytes from ctx[12])
  ctx[12]  →  "magic src"
```

`ctx[11]` / `ctx[12]` are a side-channel the original effects all
read-and-rewrite once per inner-loop iteration. Skipping the shuttle
may break downstream effects; the safe pattern is to copy verbatim. The
purpose is unknown.

The audio loop processes **8 samples per channel × 2 channels = 16
floats per call**, channel-interleaved as `LLLLLLLL RRRRRRRR`.
Implementations use a 2-iteration outer loop over channels (`MVK 2,B0`)
and 8 inline samples per inner block.

#### Provisional host state fields [hardware + stock-disassembly]

Custom hardware probes prove that `ctx[2] + 0x10` and `ctx[2] + 0x18` are
writable, persistent, and likely per-instance for at least words 0, 12, 18, and
19. `StateComb` used `ctx[2] + 0x18` words 0..15 plus word 18 as a tiny comb
history, so this block can hold small DSP state.

Stock delay/modulation disassembly and `DescComb` hardware testing confirm
`ctx[3]` as the large host-managed buffer descriptor:

```
ctx[3][0]  base pointer
ctx[3][1]  end pointer
ctx[3][2]  wrap span / byte length
```

Stock `DELAY`, `ANLGDLY`, `TAPEECHO`, and `STCHO` form sample-history addresses
from `ctx[3][0]`, compare against `ctx[3][1]`, and subtract/reload
`ctx[3][2]` when wrapping. Custom `DescComb.ZDL` first proved the descriptor is
readable/plausible (`Arm=1`, `UseBuf=0` stereo wobble), then proved descriptor
base memory is writable audio history (`UseBuf=1` sounded like a delay effect).
`DescSize` then proved the default descriptor allocation is at least 524288
bytes (`Dsz512K` wobbles), enough for the raw two-array memory requirement of
Airwindows `StereoChorus`.
`DescIso` showed two duplicate instances in separate FX slots do not see each
other's descriptor-memory stamps, so `ctx[3]` is currently treated as
per-instance.
`Dsz689K` wobbles. If the "works up to 689K" report means `Dsz690K` and higher
were silent, the default descriptor allocation is bracketed at `>= 705536` and
`< 706560` bytes. The exact byte count is no longer required for the first
`StereoChorus` exact-port attempt; the important ABI result is a per-instance
large descriptor arena of at least 705536 bytes.

### 5.3 Init `Fx_FLT_<Name>_init`

CH_2.md observed for LineSel: init calls `_onf`, `_edit_efx`, `_edit_out`
in sequence, all with a fixed magic state-pointer
(`0x80000378` for LineSel). That suggests init is called *once* with
some host-provided state, and its job is to push initial values for
each parameter into the runtime by invoking the per-param handlers.

For Exciter, init at `.text+0x5c0` (per `Fx_FLT_Exciter_init` symbol)
should follow the same pattern — invoke onf, then each edit handler.

### 5.3.b Parameter table layout [hardware-confirmed through 9 params]

`ctx[1]` points to a flat float array. Verified slots, used by
all three diy/*.asm reference effects:

```
params[0]   on/off multiplier   (1.0 when on, 0.0 when off)
params[4]   level multiplier    (= 1/max, e.g. 0.01 for max=100)
params[5]   knob 1 raw value    (0..max as float)
params[6]   knob 2 raw value
params[7]   knob 3 raw value
...
params[13]  knob 9 raw value
```

Audio code typically computes a per-knob coefficient as
`params[5] * params[4] * params[0]` once at the top of the function
(producing a normalized `0..1` scaled by on/off), then applies it
inside the sample loop.

Slots `params[5..13]` are contiguous for the 1-9 user-param range.
Generated edit handlers must write these slots; NOP handlers render UI
but do not update the audio parameters. The reusable macro lives in
`src/airwindows/common/zoom_edit_handlers.h`.

### 5.4 DLL entry `Dll_<Name>` [v1-empirical]

The ELF `e_entry` is `Dll_<Name>`. It returns:

* `B0` = address of the descriptor table **start (the OnOff entry)**,
  not the name entry.
* `A1` = address of `effectTypeImageInfo`.

Both addresses are loaded via MVK/MVKH instruction pairs that are
patched by `.rela.dyn` ABS_L16 + ABS_H16 relocations at load time.

Body length matters. v1 tried an 8-instruction (32-byte) Dll function
patterned after LOFIDLY — the unit booted but froze inconsistently on
each FX-select event. Switching to a **verbatim 200-byte (50-instruction)
copy of NoiseGate's Dll function**, with the 4 reloc points re-patched
for the new descriptor + imageInfo addresses, produced a stable boot.
The simplest working approach is therefore: splice in NoiseGate's body,
patch the relocation targets, and patch its compact `MVK A0` immediate
from NoiseGate's hardcoded descriptor count `4` to `2 + len(params)`.

### 5.5 Compile flags — the `--mem_model:data=far` trap [v1-empirical]

Critical compiler flag for any C source file used in a ZDL:

```
cl6x --c99 --opt_level=2 --opt_for_space=3 -mv6740 --abi=eabi \
     --mem_model:data=far -c your.c -o your.obj
```

Without `--mem_model:data=far`, the C compiler places small statics
in `.bss` and addresses them via **B14-relative** loads (a.k.a. SBR /
DP-relative). The Zoom firmware does *not* set B14 to a valid base
before invoking your code, so any such load reads garbage and freezes
the unit.

With `--mem_model:data=far`, every static lives in its own `.far:<name>`
section and is addressed via absolute MVKL / MVKH pairs (`R_C6000_ABS_L16`
+ `R_C6000_ABS_H16` relocations). Those *are* resolvable by the runtime
linker.

Putting the audio function into the `.audio` section is one
`#pragma CODE_SECTION` away:

```c
#pragma CODE_SECTION(Fx_FLT_<Name>, ".audio")
void Fx_FLT_<Name>(unsigned int *ctx) { ... }
```

---

## 6. Memory map and constraints

| Region     | VA                            | Flags | Notes                                        |
|------------|-------------------------------|-------|----------------------------------------------|
| `.text`    | `0x00000000` upward           | r-x   | Firmware remaps to IRAM at load time.        |
| `.const`   | `0x80000000` upward           | r--   | RO data: descriptor, image, coefficients.    |
| `.fardata` | immediately after `.const`    | rw-   | Tiny writable data. **memsz must equal filesz**. |
| Stack      | `B15` provided by host        | rw-   | Don't overflow — no MMU, no guard page.      |

* **`.fardata` must have `memsz == filesz`** [v1-empirical]. Setting
  `memsz > filesz` (i.e. requesting BSS zero-fill) overflows into
  firmware-managed memory and corrupts the parameter array, breaking
  paging. Stock effects all set `memsz = filesz` and put their
  initialised state in `.const` lookup tables, accumulating runtime
  state in a firmware-provided per-effect scratch buffer.
* The `.fardata` section's leading 24 bytes are *always*
  `_infoEffectTypeKnob_A_2 = {20, 15, 11, 0, 2, 0}`. Any user state
  follows from offset 24.
* Keep writable `.fardata` small. Stock MS-70CDR effects observed so far
  stay within a few hundred bytes; large custom static state has frozen
  hardware on effect load. The linker rejects `.fardata` images above
  512 bytes unless `allow_large_fardata=True` is set for an explicit
  hardware probe.
* **No malloc.** All state is statically allocated.
* **No FPU exceptions** worth catching — the C6740 has hardware float;
  treat NaN/Inf the same as Airwindows desktop builds do.
* **No `sinf`/`cosf`/`tanf`/`logf` in the runtime** — none of the
  stock effects use them, so they aren't in firmware's RTS. Either
  inline approximations (v1's `totape9_zoom.c` has `zoom_sinf`,
  `zoom_logf`, `zoom_tanf` examples) or table-lookups.
* **`__c6xabi_divf` (float divide) IS available** — extracted from a
  stock ZDL, ships as `build/divf_rts.bin`, gets spliced into `.text`.

## 6.1 SONAME — the `gid` trap [v1-empirical]

The `.dynamic` `DT_SONAME` string **must follow the pattern**
`ZDL_<GID_PREFIX>_<Name>.out`, where `<GID_PREFIX>` matches the
3-letter category code for the `gid` byte in the ZDL header:

| gid  | Category    | SONAME prefix |
|------|-------------|---------------|
| 0x01 | Dynamics    | `ZDL_DYN_`    |
| 0x02 | Filter      | `ZDL_FLT_`    |
| 0x06 | Modulation  | `ZDL_MOD_`    |
| 0x07 | SFX         | `ZDL_SFX_`    |
| 0x08 | Delay       | `ZDL_DLY_`    |
| 0x09 | Reverb      | `ZDL_REV_`    |

Mismatching prefix and gid causes the firmware to fall back to a
2-knob no-page render mode regardless of what the descriptor says.

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

After incorporating v1's findings and the 2026-05-13 hardware probes, the list
shrinks to:

1. **Load-safe shape for complex ports.** `ctx[3]` is proven enough for large
   per-instance state, and `StereoChorus` uses it successfully. The current
   `ToTape9` build still crashes on load, so the open problem is now the whole
   load-time shape: 9 parameters, synthesized page 2/3 edit handlers, helper
   symbols, and a larger `.audio` image.
2. The two unknown words at `effectTypeImageInfo` offsets 0x18 / 0x1C
   (Exciter has 32 / 17; LineSel has different values). Stock ZDLs all
   work with these as observed; we copy them. Their semantic role is
   irrelevant for now.
3. The `+0x18` reserved word in each SonicStomp entry — non-zero in
   delay/pitch effects only. May encode a sub-range or sub-tick value.
4. The `ctx[11]` / `ctx[12]` "magic shuttle" in the audio loop — what
   bytes are these, and what breaks if we skip the read-and-rewrite?

Lower priority — already resolved well enough for v2:

* Sample format: float32 ✓
* Sample rate: 44.1 kHz ✓
* Per-call block size: 8 samples per channel × 2 channels ✓
* C6000 calling convention: standard EABI ✓
* SONAME pattern: `ZDL_<GID>_<Name>.out` ✓
* `--mem_model:data=far` requirement ✓
* `.fardata` `memsz == filesz` ✓
* `effectTypeImageInfo` exactly 212 bytes, exactly 3 knob slots ✓
* `ctx[3][0..2]` large host-managed state descriptor ✓
* `Dll_<Name>` body: NoiseGate verbatim, 200 bytes ✓
* `KNOB_INFO = {20, 15, 11, 0, 2, 0}` ✓
