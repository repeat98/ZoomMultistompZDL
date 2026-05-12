# Zoom MS-70CDR Custom ZDL Toolchain

A from-scratch build pipeline for the Zoom MS-70CDR (and related
MultiStomp pedals) that produces loadable `.ZDL` effect files without
using Zoom's official SDK — which has never been released.

The repo holds:

* **A custom static linker** ([build/linker.py](build/linker.py)) that
  takes a TI C6000 relocatable `.obj` and emits a fully wrapped ZDL,
  including the `SonicStomp` descriptor, `effectTypeImageInfo`, the
  `.dynamic` segment, and the 76-byte Zoom header.
* **A reverse-engineered ABI document** ([build/ABI.md](build/ABI.md))
  detailing how the firmware loads and runs a plugin — symbol contract,
  parameter table, calling convention, memory layout, gotchas.
* **A ZDL/pedal RE status map**
  ([docs/ZDL-REVERSE-ENGINEERING-STATUS.md](docs/ZDL-REVERSE-ENGINEERING-STATUS.md))
  tracking the wrapper format, extended headers, stock corpus findings, and
  the remaining blockers for exact stateful ports.
* **A 1:1 Airwindows roadmap**
  ([docs/AIRWINDOWS-1TO1-PORT-ROADMAP.md](docs/AIRWINDOWS-1TO1-PORT-ROADMAP.md))
  describing the state-ABI work needed before delay, reverb, chorus, and tape
  plugins can be honest source-equivalent ports.
* **A state ABI progress log**
  ([docs/STATE-ABI-PROGRESS.md](docs/STATE-ABI-PROGRESS.md)) recording each
  hardware probe and finding so the reverse-engineering trail does not live
  only in chat.
* **A growing collection of ports** under
  [src/airwindows/](src/airwindows/) (so far: HELLO, GAIN,
  PurestDrive, TapeHack, ToTape9, BitCrush, StChorus, CtxMap). Some are exact or
  near-source kernels; state-heavy effects are clearly marked as experiments
  until the state ABI is solved.
* **Stock-derived handlers and helpers** ([build/linesel_handlers.bin](build/linesel_handlers.bin),
  [src/airwindows/common/zoom_edit_handlers.h](src/airwindows/common/zoom_edit_handlers.h),
  [build/divf_rts.bin](build/divf_rts.bin)) used to provide OnOff,
  1-9 knob edit handlers, and float-divide RTS routines.

> **Status:** the descriptor-count linker bug is fixed and hardware-tested
> up to 9 edit parameters. The release-safe path now rejects oversized
> writable `.fardata` by default, because large static plugin state has
> frozen real MS-series pedals during load.

---

## Quick start

```bash
git clone https://github.com/repeat98/ZoomMultistompZDL.git
cd ZoomMultistompZDL
python3 build_all.py             # all plugins → ./dist/*.ZDL
```

You'll need the TI C6000 toolchain installed (see "Toolchain prerequisites"
below) for any build that compiles C — the HELLO plugin doesn't, so it's
the fastest way to confirm the Python side works on your machine:

```bash
python3 build_all.py hello       # → dist/HELLO.ZDL
```

## Hardware target

* **Pedal:** Zoom MS-70CDR (firmware 2.10).
* **DSP:** Texas Instruments C674x VLIW core, 44.1 kHz, 32-bit float
  internal samples, 8 samples-per-channel block size, two-channel.
* **Effect format:** ELF32 shared object (`ET_DYN`, `EM_TI_C6000`)
  inside a 76-byte Zoom-specific wrapper.

The same pipeline likely works for any pedal in Zoom's MultiStomp family
that uses ZDLs (B1Xon, G1Xon, MS-50G, MS-60B, etc.) but only the
MS-70CDR has been hardware-tested.

---

## Toolchain prerequisites

1. **TI C6000 Code Generation Tools v8.5.0** (`cl6x` compiler, `dis6x`
   disassembler). The free download ships inside
   [Code Composer Studio](https://www.ti.com/tool/CCSTUDIO) — install
   CCS (we use 20.x) and the C6000 8.5 LTS package will be available
   under `tools/compiler/ti-cgt-c6000_8.5.0.LTS/`.

   The build scripts hard-code:

   ```
   /Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS
   ```

   On Linux/Windows or a different CCS version you'll need to edit
   the `TI_ROOT` constant at the top of each plugin's `build.py`.

2. **Python 3.10+** — no third-party packages needed; the linker is
   pure stdlib.

3. **A way to flash a custom ZDL onto the pedal.** Two options:
   * Zoom's official **Effect Manager** application (drag-and-drop UI,
     reads from a directory you point it at).
   * The community
     [Zoom-Firmware-Editor](Zoom-Firmware-Editor-master/) tool bundled
     in this repo (open the SYSTEM.BIN, swap effects, write back).

   Both are reversible — keep a backup of your factory firmware blob.

---

## Repository layout

```
ZoomMultistompZDL/
├── README.md                ← this file
├── build/
│   ├── ABI.md               authoritative runtime ABI write-up — start here
│   ├── linker.py            the static linker (.obj → .ZDL)
│   ├── zdl.py               container reader/writer + label patcher
│   ├── screen_image.py      auto-renders a 128×64 splash image from text
│   ├── linesel_handlers.bin onf + knob1 + knob2 + RTS helpers (verbatim from LineSel)
│   ├── air_knob3_edit.bin   legacy knob3 edit handler (verbatim from AIR's mix_edit)
│   └── divf_rts.bin         float-divide runtime support (verbatim from a stock effect)
├── src/
│   └── airwindows/
│       ├── hello/           proves the build/flash/boot loop works end-to-end
│       ├── gain/            single-knob volume trim — minimal C plugin
│       ├── purestdrive/     Airwindows PurestDrive port (1 knob)
│       ├── tapehack/        Airwindows TapeHack port
│       ├── totape9/         Airwindows ToTape9 stateless beta (9 params)
│       ├── bitcrush/        bit-depth/sample-rate crusher (1 knob)
│       └── stereochorus/    Airwindows StereoChorus state/ABI experiment
├── build_all.py             rebuild every plugin into ./dist/
├── dist/                    output ZDLs land here (point Effect Manager at this)
├── working_zdls/            stock factory ZDLs — used as references and templates
├── airwindows-ref/          full Airwindows source tree (read-only reference)
├── zoom-fx-modding-ref/     community RE notes and disassembly walkthroughs
└── ZoomPedalFun-main/       independent RE of firmware structures
```

---

## Build a plugin (end to end)

```bash
# rebuild everything into dist/
python3 build_all.py

# rebuild one plugin
python3 build_all.py tapehack

# or run a plugin's build script directly
python3 src/airwindows/tapehack/build.py
```

Each plugin's `build.py` does two things:

1. Invokes `cl6x` to compile the plugin's `.c` file into a TI relocatable
   `.obj` (with the critical `--mem_model:data=far` flag — see
   [build/ABI.md](build/ABI.md) §5.5).
2. Calls `linker.link(LinkerConfig(...))` to wrap the `.obj` into a ZDL.

The linker reads a `manifest.json` next to each plugin source so the
config travels with the plugin rather than with `build.py` (see below).

---

## Adding a new effect — a 5-step recipe

1. **Pick a directory name** (e.g. `myrev/`) under
   [src/airwindows/](src/airwindows/) and copy
   [src/airwindows/gain/](src/airwindows/gain/) as a starting
   skeleton.

2. **Write the DSP.** Replace `gain.c` with your own. The required
   signature is:

   ```c
   #pragma CODE_SECTION(Fx_FLT_<Name>, ".audio")

   void Fx_FLT_<Name>(unsigned int *ctx) {
       float *params = (float *)(uintptr_t)ctx[1];
       float *fxBuf  = (float *)(uintptr_t)ctx[5];   /* signal in/out (wet path) */

       /* Magic shuttle — copy verbatim, purpose unknown but skipping
        * breaks downstream effects. */
       unsigned int *magicSrc = (unsigned int *)(uintptr_t)ctx[12];
       unsigned int *magicDst = (unsigned int *)(uintptr_t)
           *(unsigned int *)(uintptr_t)ctx[11];
       *magicDst = *magicSrc;

       if (params[0] < 0.5f) return;              /* OnOff bypass */

       /* params[5] = knob 1, params[6] = knob 2, params[7] = knob 3,
        * each scaled to ~0..0.14 by the spliced edit handlers. */

       for (int i = 0; i < 16; i++) {             /* 8 L + 8 R per call */
           fxBuf[i] = process(fxBuf[i], params[5], params[6], params[7]);
       }
   }
   ```

   See [build/ABI.md §5.2–§5.4](build/ABI.md) for buffer-state details
   and the calling convention.

3. **Edit `manifest.json`.** Fields:

   | field              | type     | meaning                                                      |
   |--------------------|----------|--------------------------------------------------------------|
   | `effect_name`      | string   | ≤12 chars, used in symbol names and the on-screen label.     |
   | `audio_func_name`  | string   | usually `Fx_FLT_<Name>` (must match the `#pragma CODE_SECTION`). |
   | `gid`              | int      | category (1=Dynamics, 2=Filter, 6=Modulation, 8=Delay, 9=Reverb…). |
   | `fxid`             | int      | uint16 effect ID; pick something not used by stock effects (≥0x190 is safe). |
   | `fxid_version`     | string   | 4-char version, e.g. "1.00".                                 |
   | `flags_byte`       | int      | ZDL header byte 0x3D; usually 0x01.                          |
   | `params`           | array    | one entry per knob (1–9 entries — see "Knob limits" below).  |
   | `audio_nop`        | bool     | optional — if true, replace the audio func with a B B3 stub for UI smoke-testing without DSP. |

   Each `params` entry has:
   * `name` (≤ 8 ASCII chars — short labels render best),
   * `type` (`knob`, `switch`, `enum`, or `tempo`; currently used as metadata and for generated DSP constants),
   * `min`, `max`, `default` (UI integer range written into the descriptor),
   * optional descriptor fields: `pedal_max`, `flags`, `reserved_a`, `reserved_b`,
   * optional DSP fields: `scale`, `unit`, `audio_min`, `audio_max`, `audio_default`, `labels`,
   * `comment` (free-form, ignored by the linker).

   Manifest builds generate an `<effect>_params.h` header when the build
   script calls `write_param_header(...)`. DSP code can then use
   `ZOOM_PARAM_*` helpers from
   [src/airwindows/common/zoom_params.h](src/airwindows/common/zoom_params.h)
   instead of hardcoding every slot/default/range.

4. **Add an entry to `build_all.py`.** Append your plugin to the
   `PLUGINS` list so it gets rebuilt with the rest:

   ```python
   PLUGINS = [
       ...
       ("myrev", PLUGIN_DIR / "myrev" / "build.py"),
   ]
   ```

5. **Build, copy, flash.**

   ```bash
   python3 build_all.py myrev
   cp dist/MyRev.ZDL <where-Effect-Manager-watches>
   ```

   Use the Effect Manager (or the bundled Firmware Editor) to flash.
   Open the FX menu on the pedal and look for your effect under its
   `gid` category.

---

## Knob limits — what works, what's an experiment

The pedal paginates parameters onto **3 fixed visible slots** by walking
the descriptor table 3 entries at a time. So a 9-knob plugin shows up as
3 pages of 3 knobs each. We accept up to 9 `params`.

| # of knobs | Status             | Edit handlers used                              |
|-----------:|--------------------|-------------------------------------------------|
| 1          | verified           | LineSel-compatible write to `params[5]`         |
| 2          | verified           | LineSel-compatible writes to `params[5..6]`     |
| 3          | verified           | Generated writes to `params[5..7]`              |
| 4-9        | verified in UI path | Generated writes to `params[5..13]`             |

The 2026-05-11 fix was in the DLL entry stub: it must declare
`OnOff + effect-name + params` descriptor entries. Copying NoiseGate's
hardcoded count of `4` made edit mode stop after two user params. See
[docs/3-PARAM-LINKER-BUG.md](docs/3-PARAM-LINKER-BUG.md) for the
investigation log.

For knobs beyond the first two, include
[src/airwindows/common/zoom_edit_handlers.h](src/airwindows/common/zoom_edit_handlers.h)
and instantiate `ZOOM_EDIT_HANDLER(symbol, knob_id, param_byte_offset)`.
ToTape9 is the reference 9-param build.

---

## Going deeper

* **[build/ABI.md](build/ABI.md)** is the single most load-bearing doc
  in this repo. Every magic constant in the linker has a `[v1-empirical]`
  marker pointing back to the experiment that pinned it down. Read it
  before changing the linker.
* **[build/linker.py](build/linker.py)** is heavily commented. The
  `LinkerConfig` dataclass is the public API; everything else is
  implementation detail.
* **[zoom-fx-modding-ref/library/CH_2.md](zoom-fx-modding-ref/library/CH_2.md)**
  walks through a stock effect's audio loop in disassembly. The
  buffer-pointer convention this repo uses comes from there.
* The full Airwindows source ([airwindows-ref/](airwindows-ref/)) is
  bundled for porting reference — most kernels are sample-by-sample C
  that drops in once you account for the L/R interleave (8L + 8R).

---

## Contributing

* Bugs/proposals: open an issue.
* Hardware test results — even a paragraph saying "I flashed a 4-knob
  plugin and knob 4 does/doesn't modulate audio" — are extremely
  valuable; see [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) for the
  open-questions list.
* The iterative-flow rule: if you change the linker, rebuild *one*
  plugin, flash it, confirm boot before changing anything else. Stock
  ZDLs were our only source of truth before any of these plugins booted;
  hardware behavior is still the only source of truth for anything
  marked `[ASSUMPTION]` in the ABI doc.

## Licence

The code in this repository (linker, build scripts, ports) is MIT.
Bundled reference material (Airwindows source, Zoom Firmware Editor,
stock ZDLs in `working_zdls/`) is owned by their respective authors and
included for research/RE purposes.
