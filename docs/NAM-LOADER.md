# Load multiple NAM captures (and cab IRs)

> **Beta.** Tested on one MS-70CDR only. If you try it on another model, please
> file a [NAM / Cab report](https://github.com/themanro/ZoomMultistompZDL/issues/new?template=nam-cab-report.yml),
> including when everything works.

## Before you start

- **You don't need a firmware update** to use the loader or this project's
  effects. The MS-70CDR here runs firmware 2.10.
- **If you do update firmware: close Zoom Effect Manager first, and never
  unplug during the update.** Zoom's own updater also rewrites the part of the
  pedal that holds update mode, so cutting it off early can leave the pedal
  needing a repair.
- **The "+" models (MS-50G+, MS-60B+, MS-70CDR+) and the Four series are not
  supported.** If Effect Manager looks different from the guides, check your
  model first. For NAM on a "+" pedal, use [nam2zoom](https://github.com/freelender/nam-to-zoom)
  (MS-50G+ and MS-70CDR+ tested, MS-60B+ experimental).
- Back up your patches.

## If the pedal freezes

A bad effect file can stop the pedal from finishing boot, or freeze it when a
patch uses the effect. It is recoverable, and in testing it always was:

1. **Remove the last file you installed.** Zoom Effect Manager can still reach
   a pedal that will not boot: start the pedal in **firmware update mode** by
   holding the **Up and Down buttons while plugging in the USB cable** (the
   screen may look blank or odd), connect Effect Manager, delete the effect
   you added last, and write. The same mode runs Zoom's firmware updater if
   the firmware itself is damaged, such as after an interrupted update.
   (Button combo as documented by [MIDISTOMP](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/user-guide.md#3-recovery-and-going-back-to-stock),
   tested there on an MS-60B.)
2. **If a saved patch freezes it** (boots fine until that patch loads): remove
   or replace the effect the same way. Patches that used it come back with that
   slot empty.
3. **Last resort — erases all your patches:** power off, hold the **leftmost
   knob pressed in**, power on, choose `All INITIALIZE`, press the footswitch.

Things that are known to freeze it, so you can avoid them:

- Two effect files whose names are the same in their first 8 characters.
  The loader's file names (`NAM4smok.ZDL`, `C01sm57.ZDL`) are built to avoid
  this; don't rename them.
- An effect file over about 32 KB. Loader output is always under the limit.
- An old `NAMLite-<name>.ZDL` from before 2026-09-29 (see below).

Whenever you report a freeze, say which files were installed and which one you
added last.

> **Filenames changed (2026-09-29): captures are now `NAM<slot><name>.ZDL`,
> e.g. `NAM2smok.ZDL`.** The old `NAMLite-<name>.ZDL` files all cut down to
> `NAMLite-` on the pedal (it keeps 8 characters), and two installed files with
> the same cut-down name freeze it on boot. Remove any `NAMLite-…` capture files
> from the pedal and install the renamed ones. The 0.23 engine was not at fault.
> **Hardware-confirmed 2026-09-29:** `NAM1ampt` + `NAM2smok` installed together
> boot fine (with CabIR also installed).
>
> **Calibrated DSP estimates (2026-10-06).** Current captures declare full-rate
> NAM 194, Eco 6/8 NAM 177 (181 from 0.26; Eco+ 152), and CabIR 10. PE uses an approximate budget of 228;
> hardware accepted a declared total of 224.4 and refused 228.4. These costs
> help the pedal reject oversized chains with **DSP Full**, but are admission
> estimates, not measured CPU usage or a guarantee against crackling while
> turning controls. Re-export and reinstall captures to use the current costs.
>
> **216 slots, your icon and name on the pedal screen (2026-10-16).** Slots
> 17-216 for captures are FXIDs 500-699 and for cabs 700-899 (1-16 are
> unchanged). They are made in the browser from one base template per engine
> (`tools/slot_identity.js`): a slot differs from another only in its FXID, the
> slot digits in its name and the ELF hash table those names feed, and the
> tests check generated slots against linker-built ones byte for byte. Every
> template now reserves 1,024 bytes for the cover, which the loader fills with
> the chosen icon and name (`tools/cover_art.js`); the Effect Manager
> thumbnail is drawn from the same picture. Re-export a capture to get its
> name and icon on screen; older files keep working as they are. Filenames:
> `NAM<slot><name>` with 4/3/2 name letters for slots 1-9/10-99/100-216;
> cabs `C<slot><name>` with 5 letters, 4 from slot 100. Cab names must now
> start with a letter.
>
> **16 capture slots (2026-10-06).** Slots 1-8 keep FXIDs 900-907; slots 9-16
> are 950-957 (908-913 were the retired CabIR bank and NAM test effects).
> Files `NAM<slot><name>` (4 name characters for slots 1-9, 3 for 10-16, e.g.
> `NAM12amp.ZDL`); short names must start with a letter so slot 1 can never
> collide with slots 10-16 on the pedal's 8-character names. Patch Editor lists
> only the captures and cabs you have made (named via this browser's loader or
> files in dist/), not the empty reserved slots.
>
> **Engine 0.26 (2026-10-19, hardware-tested the same day).** Three choices in the
> loader: **Full rate** (194), **Eco** (181) and **Eco+** (152).
> - Soft output limiter: exact below 0.75, then a smooth curve to full scale,
>   instead of the hard clip at 1.0.
> - Eco resamples with cubic curves at evenly spaced positions. Its spurs went
>   from -23 dB to -53 dB at 3 kHz.
> - Eco+ runs the model at half rate. The page measures the capture at full
>   rate and at half rate, at three playing levels (`nam_response.js`
>   `fitEcoEq`), fits a high shelf and two peaks, and writes them into the
>   file. In the emulator: medium playing within ±1 dB of full rate up to
>   5 kHz, soft and hard playing within ±2.8 dB, 24% fewer cycles.
>
> **Split outputs (0.26).** The loader's **Outputs** choice: Stereo (the amp on
> both), or Split, the amp on one output and the dry guitar on the other.
> - Which side gets the amp is written into the file, as two factors (the amp
>   share of L and of R) over a table the loader finds by its marker
>   (`split_route_offset`; `nam_split_route` in namlite.c).
> - Knob 3 becomes **Dry**: the dry side's level, -24 to +24 dB in about
>   0.5 dB steps, 50 = unchanged, smoothed. The amp side is always fully wet.
> - Full rate only, 194, the same file size. Templates:
>   `tools/nam_template_split/`. Patch Editor shows knob 3 as Dry for
>   captures exported as split.
>
> **Hardware (2026-10-19):** full, Eco, Eco+ and split (NAM213Pl / NAM214Pl,
> BRIT50 Plexi, both sides) all load and play on the owner's MS-70CDR. Eco+ sounds audibly worse than full rate: it is a
> trade, there when the DSP is needed for other effects.
>
> Templates: `tools/nam_template_ecoplus/`. Details:
> [NAM-RUNTIME-INVESTIGATION.md](NAM-RUNTIME-INVESTIGATION.md), 2026-10-19.
>
> **Engine 0.25 (2026-10-02).** 51-row Bass/Mid/Treb table (3 KB smaller; odd knob
> values play the next even one), flat-EQ skip, and an **Eco** checkbox: the model
> runs 6 of every 8 samples (~6% less DSP; within 0.7 dB of full rate through a cab) for amp-only captures going into a cab.
> Eco templates: `tools/nam_template_eco/`.
>
> **Engine 0.24 (2026-10-02, rebuilt).** The first 0.24 froze the pedal on load: it was
> over the ZDL size cap (see SAFE-DSP-RULES.md). This one is smaller than 0.23.
> ~4% lighter than 0.23 (predicate-free input and
> output loops once warm), so NAM + CabIR has more room; sound within rounding
> (~90 dB) of 0.23. Re-export captures to get it.
>
> **Engine 0.23 (2026-09-28).** Adds a **Gate** knob (page 3) that mutes the
> amp hiss between notes; Gate 0 is off and bit-identical to 0.22. Engine 0.22
> was the same sound as 0.21, bit for bit, with about 21% less DSP work. Every capture the loader makes now plays at full
> rate with the full model (23 layers × 3 channels, all 1,871 weights, 32-bit
> float), and has **Bass / Mid / Treb** on the second knob page. Captures made
> with the old 0.14 engine crackle at full rate; 0.21/0.22 captures work but use
> more DSP or lack the gate — re-export to upgrade.
> No captures ship with the repo: bring your own `.nam` (e.g. from
> [TONE3000](https://www.tone3000.com/)) and build it with the loader.

1. Start the local Patch Editor. Open **Settings → Custom NAM captures → Open NAM Loader**.
2. Choose a compatible `.nam` file.
3. Give it a short name (1–8 ASCII letters, numbers, hyphens or underscores),
   such as `smokey`. Choose an unused capture slot.
4. Click **Create pedal file**, then download **NAM2smok.ZDL** (slot 2 here) and its
   capture notes. Install the ZDL through Zoom Effect Manager.
5. Repeat with another file and another slot. Both can remain installed.
6. Close Effect Manager and reconnect PE. PE calls the effect `NAMLite-smokey`;
   the pedal uses the shorter `NAM-smokey` under Delay, version **0.25**.
7. Compare captures one at a time, initially Input 50 / Output 25 / **Mix 100**
   (Mix starts at 0, and at 0 the model does not run).

## Cabinets (CabIR)

The same page has a **Cabinets** section. Each cab IR WAV (44.1/48 kHz, up to
2 s) is fitted in the browser to a 32-tap FIR + 6 filters and becomes **its own
CabIR effect**, like a NAM capture: up to 216 slots (FXID 930-945, then 700-899), files
`C<slot><name>.ZDL` (e.g. `C01sm57.ZDL`), pedal name `CAB-<name>`, picked
from the slot's effect list -- no Cab knob. A cab keeps its slot; removing one
frees the slot for the next. Download one cab or all; install with Effect
Manager. Cost ~800 cycles (~5% of NAM). Details:
`src/hardware_probes/cab_ir/README.md`.

## Frequency response

Below the capture, **Frequency response** plots how the capture shapes the
tone, measured in the browser (`tools/nam_response.js`): the page runs the
capture's network on pink noise at three input levels (−30, −18 and −6 dBFS
RMS, soft to hard playing) and shows, for each, the part of the output that
follows the input (H = Sxy/Sxx, 1/6 octave). The curves are levelled in the
mids so their shapes compare; the legend gives each level's gain, so the
compression shows too. Pick a cab from your bank to see the chain as the pedal
plays it (the capture, then the cab's pedal filter); with no capture loaded,
a cab shows its IR against that filter. A 48 kHz capture can also be shown as
trained, next to the 44.1 kHz the pedal plays it at. The page's network
matches the C kernel `tools/nam_prototype/generate.py` writes (checked
against NAM Core) to 2e-7; the tone stack and gate are not included.

## Knobs

| page | knobs |
|---|---|
| 1 | Input, Output, Mix |
| 2 | Bass, Mid, Treb — 50 is exactly flat |
| 3 | Gate — 0 is off; 1–100 sets the threshold from −99 to −30 dB |

The tone stack is voiced like the NAM plugin's: Bass a low shelf at 150 Hz
(±20 dB), Mid a peak at 425 Hz (±15 dB), Treb a high shelf at 1.8 kHz (±10 dB),
run in that order after the model. At 50/50/50 the output is bit-identical to
the same capture without an EQ. It costs ~1.8% of the DSP whatever the settings.

## DSP headroom

At full rate one capture uses most of the pedal's DSP: it declares 194 of the
roughly 225 the pedal allows, Eco 181, Eco+ 152, a cab 10 (0.26). On the owner's MS-70CDR a
full-rate capture plus one light effect (Great Muff, or a cab) plays clean.
Patch Editor's DSP meter adds the chain up before you write it. How the full rate was made to fit at all is in
[NAM-RUNTIME-INVESTIGATION.md](NAM-RUNTIME-INVESTIGATION.md).

## Capture slots and names

216 independent identities are reserved (FXIDs 900–907, 950–957 and 500–699, Delay group). These
were checked against the current stock, custom, legacy and probe database and
source manifests. Original NAMLite (498) is unchanged. Merely renaming a file
would not create another effect; each slot has its own ID and DLL identity.

Reusing a slot replaces that capture in every patch referencing it, even if you
choose a new short name. The page identifies occupied slots and prevents duplicate
short names across slots. Same-file reexports select their previous slot; new
files select the first locally unused slot. When all slots are occupied, choose
which one to replace. Creating a download does not install or replace anything
on the pedal.

Names and occupancy are stored in this browser at this address. Keep the same
browser and URL (localhost and 127.0.0.1 are different origins). Browser storage
is not a pedal inventory. Another browser/computer or cleared storage cannot
know your occupied slots: use saved capture notes before choosing a slot. PE
recognizes every slot ID even without these names, as generic numbered captures.
It updates names when returning from the loader or receiving a storage update.

This enables keeping several captures installed, not a guarantee that multiple
neural effects can process simultaneously within the pedal's DSP budget.

## Compatibility

Conversion stays in the browser, without a compiler or upload. Open via localhost
or HTTPS rather than file://. Install through Effect Manager on a computer;
PE cannot install `.nam` files directly.

Only the supported 3-channel A2 Lite WaveNet layout is accepted, either directly
or as a matching SlimmableContainer submodel. The page checks shape, activations,
coefficient count and finite values. Bigger networks, LSTMs and other shapes
are rejected. File limit is 20 MB.

44.1 and 48 kHz captures are accepted. Playback remains native 44.1 kHz without
resampling, so 48 kHz captures can differ from their original tone and timing.
For an amp-only 48 kHz capture the difference is small (within about ±1 dB in
our measurements). A capture with a cab built in can be off by several dB,
because its resonances move. Prefer the amp-only version plus a CabIR cab: the
cab loader resamples 48 kHz IRs properly. The **Frequency response** view can
show a 48 kHz capture as trained next to how the pedal plays it. A true
48 kHz mode was built and measured, and doesn't fit the DSP (see
NAM-RUNTIME-INVESTIGATION.md, 2026-10-19).
Wet is mono. Hardware fidelity remains experimental.

## Verification

**Engine 0.23** (0.22 + gate; 0.22 = 0.21 + register-accumulated tap loops). Templates are packaged by `tools/nam_prototype/package_eq_templates.py`
(the old `package_multi_templates.py` refuses to run: it would restore the
crackling 0.12 engine). Checks: the audio code is byte-identical in all eight
slots; the seed capture's weights occur exactly once and are zeroed; slot 1
filled by the loader's own `convertNamed` is **byte-identical** to a direct
build of the same capture; that file runs clean in the emulator (no resets,
mirror invariants hold) and, with the EQ flat, its output is bit-identical to
the NAMFull2 engine and to the 0.21 capture 1 (also at EQ 90/20/70 and
0/100/0). Emulated callback: 15,763 cycles median vs 20,011 for 0.21; the gate adds
~170 (15,933 with Gate 0, 15,950 with it on). Gate 0 is bit-identical to 0.22
(EQ flat and 90/20/70); with the gate on the TI build matches the host build
to 1e-10. `validate_tone_stack.py` step 4 covers the gate. `validate_exact_rings.py` and `validate_tone_stack.py`
cover the kernel and EQ on the host. The 0.14 templates are archived in
`build/nam-archive/2026-09-28/nam_template-0.14/`; the 0.21 and 0.22
templates and capture 1 in `nam_template-0.2x/` and `capture1-0.2x/`.

**Engine 0.14 (historical):**

Eight templates are linked from the tested Smokey 0.12 object, with distinct
IDs and DLL/SONAME identities. Their DSP instructions are byte-identical to the
working block build. Capture coefficients are zeroed before packaging; no
capture is bundled. Browser conversion changes only weights, version and the
12-byte display-name field. All other code, relocations and tables stay intact.

Automated tests verify unique IDs, restricted writes, names, registry replacement,
unsupported models and damaged templates. Multi-capture installation was
confirmed on hardware 2026-09-29 once filenames were kept to 8 characters. Original single-identity conversion remains covered by
byte comparisons with previously tested Smokey and Megaphone binaries.

`tools/nam_prototype/package_multi_templates.py` creates the reserved templates
and PE entries. `build/extract_effect_db.py` preserves their metadata during
normal DB rebuilds. The capture-free engine binaries are not installable effects
until the browser fills their model data.

Tests: `node --test tools/tests/nam_loader.test.cjs tools/tests/patch_editor.test.cjs`.

### Generic capture artwork

Every new export embeds the native 128×64 NAM cover. The result also offers a
same-name PNG for Effect Manager; save it beside the ZDL. Existing installed
captures need to be exported and installed again to receive the cover.
The artwork source is `build/capture_art.py`; both template packaging scripts
include it and verify that DSP instructions remain unchanged apart from relocated
constant addresses.
