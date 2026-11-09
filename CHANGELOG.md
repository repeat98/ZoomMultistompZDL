# Changelog

What changed, newest first. The project has no version numbers; entries are
dated. Effects in [dist/](dist/) carry their own version in the file
(shown in Zoom Effect Manager).

## Unreleased

### Effects
- **Spool** has a new effect ID, 914 (was 409), as version 1.02; the sound is
  unchanged. TEcho4.ZDL from another collection used 409 too, and swapping
  the two in Zoom Effect Manager froze an MS-70CDR at boot until its ROM was
  reprogrammed. To update: remove the old Spool, power-cycle, then install
  the new one ([steps](docs/INSTALLING-ZDLS.md#spools-new-effect-id-29-october-2026)).
  Patches with the old Spool need it picked again. The Patch Editor still
  reads them (as "Spool (old 409)"), can remove the old file, and refuses to
  write the new ID over it in place.

### Patch Editor
- **Effects**: install, update and remove this project's effects over USB
  on the MS-70CDR, without Zoom Effect Manager. It shows the version on the
  pedal next to the one available, refuses Zoom's own effects and any name
  or effect-ID clash, checks downloads against `dist/index.json` (written by
  `build/dist_index.py`), reads back every write, writes the effect before
  the effect list, and backs up all the pedal's files on request. Tested on
  the owner's pedal (2026-10-23): remove, power-cycle, install, power-cycle.
- **Zoom's effects from Zoom's updater**: in Effects, choose the firmware
  updater you downloaded from Zoom (the Mac `.zip`, or its `FS.bin`). The
  page unpacks it and strips each effect as Effect Manager does
  (`tools/zdl_strip.js`, byte-identical to TI's strip6x on all 137 MS-70CDR
  2.10 effects), all in the browser, nothing uploaded. It lists the effects
  missing from the pedal or newer than its copy, and installs only those:
  never an older version over a newer one, never in place of another effect.
  Not yet tested on a pedal.
- **NAM captures** in Effects: choose a .nam and a short name, and the
  capture is converted (the NAM loader's engine, Full rate or Eco) and
  installed over USB in one step, as a new capture (the next unused slot ID,
  picked for you) or in place of one already on the pedal, which is removed
  first. Patches using that slot then play the new capture.
  Cabs the same way: choose a .wav IR and a name; it is fitted (the cab
  loader's fit, in a worker) and installed as a new cab or in place of one.
  A DSP estimate shows the capture's share of the pedal (194 or 181 of
  ~228), what still fits beside it, and whether it fits the open patch.
  Captures and cabs on the pedal are listed with Remove. Eco+, split outputs
  and cabs are still made in the NAM + Cab Loader. Not yet tested on a pedal.
- **NAM / Cab** is its own panel (a menu button in both editors): captures and
  cabs on the pedal, install from a file or from **TONE3000** (pick in
  TONE3000's own browser after signing in there; the capture or IR loads
  straight into the page, credited to its creator; once signed in, your
  TONE3000 favourites and pasted tone links load without the popup), the DSP
  estimate, and a
  link to the NAM + Cab Loader for making files. It replaces the NAM section
  in Settings and the loader panel in editor.html.
- **Packs** in NAM / Cab: a TONE3000 tone with several models (gain stages,
  mics), or several files chosen at once, installs as one pack: tick the
  variants, and they get family names (a pack code plus what sets each apart,
  e.g. MP3, MP5, MP10 for Gain 3/5/10, distinct on the pedal's screen). After
  every install the editor groups its captures and cabs in the pedal's effect
  list (pack by pack, variants in number order), leaving every other effect's
  place alone.
- **Variant switcher**: a slot holding a capture or cab from a pack shows
  ◀ name · 2/4 ▶ under its effect; stepping swaps in the next variant of the
  pack (only those on the pedal, once it has been read), keeping the slot's
  knob values, so gain stages can be auditioned in place.
- **[editor.html](tools/editor.html)**: the Patch Editor in Modwerk's design,
  running the same code. In testing; the classic editor stays the default.

### In dist/
- **Loop 0.03**: with Long turned on while a loop is recorded, the screen
  now says **CLEAR** (Long is available once the looper is cleared) instead
  of NO LONG, which now only means Long can't be used here (other firmware,
  or MIDISTOMP installed). Tested on the MS-70CDR 2.10 (2026-10-23).
- **Installing over USB without Effect Manager** works on the MS-70CDR 2.10
  (first tests, 2026-10-23): `tools/file_probe.html` backs up every file
  from the pedal, and replaced Loop 0.03 with 0.02 and back, each loaded
  after a power cycle. See docs/EFFECT-INSTALL-PROTOCOL.md.
- **Loop, Skull, Scope, Spectrum and Ring** now ship in `dist/`, tested on
  the MS-70CDR 2.10 (2026-10-20): Loop 0.02, Skull 0.05, Scope 0.03,
  Spectrum 0.02, Ring 0.02. Their screens need firmware 2.10; elsewhere they
  run as audio effects (Loop) or pass the sound through.

### NAM engine 0.26 (works on the pedal)
- **Eco+**: half-rate NAM, with a correction EQ the loader fits to each
  capture: 152 instead of 194, for amp-only captures into a cab. It sounds
  worse than full rate: use it when the DSP is needed for other effects.
- **Eco** resamples with cubic curves at evenly spaced positions, so its
  whistle-like spurs drop by 30-45 dB. It costs 181 instead of 177.
- **Soft output limiter** instead of the hard clip at full scale.
- **Split outputs**: the amp on one output, the clean guitar on the other
  (for a second amp or a DI). Pick the side in the loader. Knob 3 becomes
  **Dry**, the dry side's level, -24 to +24 dB with 50 = unchanged. Full
  rate only, same file size and DSP cost (194). Works on the pedal.

### Emulator
- Fixed a Ziddle decoding bug (local copy): a masked 16-bit stack store in a
  pipelined loop counted as unit D1 instead of D2, so it was replayed on every
  iteration and overwrote a saved pointer.
- Two more Ziddle fixes (local copy): the 16-bit shift-by-constant decoded
  "shift by 8" as 7 and "by 16" as 0 (45 such instructions in our builds),
  and SPLOOPW loops ran an iteration too many after their exit condition. The split build still disagrees with
  the host in the emulator but plays correctly on the pedal; see
  docs/NAM-RUNTIME-INVESTIGATION.md.

### README art
- New hero: the console painting with all its detail, in the screens'
  pale-blue phosphor, its red LEDs kept (`graphics/make_phosphor_hero.py`).
- The effects overview shows every effect: the pack, the experimental effects
  (live screens as they play), a NAM and a CAB example, and the Matujuice pack
  in a credited band. Thumbnails for all of them in the README.
- The Patch + Cover Editor image is re-shot from the current pages.
- One list of what the README shows, for both generators: `build/readme_art.py`.

### Library
- The **Matujuice effects pack v1.5** by Luca Matturro is included in
  `dist/`, credited, with its licence. The Patch Editor lists it under his
  name.

roughly 225 the pedal allows, Eco 181, Eco+ 152, a cab 10 (0.26).
### NAM + Cab Loader
- **Frequency response**: the capture's EQ curve at three playing levels,
  through any cab in your bank, or a cab's IR against its pedal filter; 48 kHz
  captures can be shown as trained. Measured in the browser
  (`tools/nam_response.js`, matched to the validated C kernel).

### Loop v0.02 (experimental)
- **Tempo quantize**: Tempo (BPM, 40-250) and Beats (per bar; Off = free)
  set before recording snap the loop to whole bars: an early closing press
  records on to the bar line, a late one drops the overshoot and plays on in
  time.
- **Click**: a metronome with a bar accent, in the output only (never
  recorded), with its own level knob.
- Screen shows the BPM, then bar and beat. Matches the host build in the
  emulator in every session tested, and works on the pedal (2026-10-20).

### Visual effects (experimental, MS-70CDR firmware 2.10)
- **Full screen**: Scope v0.03, Spectrum v0.02 and Ring v0.02 draw over the
  whole display, with no knob row; the knobs are on the knob pages.
- **Skull v0.05**: the knob boxes stay hidden. They came back on the pedal in
  v0.04 because the hide ran only once, at start-up; it now runs every callback.
- **Skull v0.04**: idle animations when it's quiet (looks around, spins, a
  snake through the eye sockets and mouth, rolls, melts into dust); a more
  violent explosion of shards cut from its own picture.
- **Spectrum** (FXID 468): a live spectrum analyzer, 1024-point FFT, 126 bars
  40 Hz - 16 kHz with peak hold; Range, Fall and Tilt.

### Loop
- **Loop** (FXID 467): a looper on stock firmware; works on the pedal. The
  footswitch records, plays and overdubs; a double press stops, and a double
  press when stopped clears. Undo and redo of the last overdub; mono, 12-bit,
  ~5 s (Long: ~23 s in RAM MIDISTOMP found unused on 2.10, experimental). Its
  screen shows the state, the time and the loop's waveform with a playhead.
  Guide: [src/custom/loop/README.md](src/custom/loop/README.md).
- README: a section for the looper and the live screen effects.

## 2026-10-18

### NAM + Cab Loader
- **216 capture slots and 216 cab slots** (was 16 each). Slots 1-16 keep
  their effect IDs; captures 17-216 are FXIDs 500-699, cabs 700-899. Slots
  past 16 are made in the browser from one base template per engine
  (`tools/slot_identity.js`); tests check them byte for byte against
  linker-built files.
- **Your name and an icon on the pedal screen.** Pick one of 21 icons (amp,
  cabinet, speaker, tube, mic, skull, flame, ghost…); the pedal-screen picture
  shows it next to the name you typed, and the loader gives you a matching
  Effect Manager thumbnail (`tools/cover_art.js`, `build/capture_icons.py`).
  Every template reserves 1,024 bytes for this picture. Re-export a capture
  to get its name on screen; older files keep working.
- Amp and cab cards now work the same way: name, icon, slot picker and
  preview, with the preview hidden until a file is chosen.
- New filename rules: `NAM<slot><name>` (4/3/2 name letters for slots
  1-9/10-99/100-216); cabs `C<slot><name>` (5 letters, 4 from slot 100).
  Cab names must start with a letter; digit-first names are migrated.

### Patch Editor
- Knows all 432 generated slots, and draws each capture's and cab's own
  name and icon on its card.

### Toolchain
- **Linker fix: calls between code sections.** A call from one code section
  to a function in another landed past its target (the instruction's offset
  was added twice). This froze the pedal when the Blink probe was selected,
  and probably explains an older report on another effect. The linker now
  handles it, or refuses to link when it can't be sure, following Leemuzhko's
  SDK notes. Tonic rebuilds byte-identical.
- The linker can hand an effect the addresses of its own picture and
  picture info (`_<audio>_Pic`, `_<audio>_Info`), so an effect can redraw
  itself.
- Effect DB: generated slots are listed by range rather than one by one.
- Builds of the animated effects and probes write their Effect Manager
  thumbnail too.

### Animated screens (experimental, MS-70CDR firmware 2.10 only)
An effect can now animate its own pedal screen on stock firmware: no
firmware flash. Research and hardware results:
[docs/pedal-research/animated-covers.md](docs/pedal-research/animated-covers.md),
with thanks to Alexander Lim (Leemuzhko) for the SDK notes that pointed the
way.
- **Probes** (`src/hardware_probes/redraw`, `coverrw`, `blink`): proved
  that the screen redraws only on events, that an effect can rewrite its
  own picture, and that an effect can ask for a redraw. All three were run
  on the pedal.
- **zvis kit** (`src/custom/common/`): draw a 128×64 frame, encode it a
  little per audio block, show it at ~30 fps, only while the effect's card is
  on screen. Firmware addresses are checked first; on any other firmware the
  effect is just a pass-through.
- **Scope** (FXID 414): a live oscilloscope of the input. Works on the pedal.
- **Ring** (FXID 415): a rotating ring that follows the signal. Works on
  the pedal.
- **Skull** (FXID 416): a shaded 3D skull, full screen, that opens its jaw,
  lights its eyes and shakes with the signal, and explodes at the loudest
  peaks (Boom knob). Works on the pedal.

These three are built locally and are not in `dist/` yet.

### Docs and graphics
- The README's main image is redrawn in the Skull's 1-bit dither
  (`graphics/14-console-dithered.png`, made by
  `graphics/make_dithered_hero.py`; 36 KB instead of 2.9 MB). Replaced on
  2026-10-19 by the phosphor hero (see Unreleased).
- NAM Loader guide, NAM template docs and the reserved effect ID list
  updated for 216 slots, names and icons.
- This changelog.

## 2026-10-14
- MS-50G firmware 3.10 confirmed: NAM (full rate and Eco), CabIR and the
  Patch Editor's writes all work (#5).
- Effect DB decodes the pedal's "Hz" glyph, so Graphic EQ is recognised.

## 2026-10-12
- Loader caps on-pedal names at 9 characters (`NAM-`/`CAB-` + 5 letters).
- Pedal research notes for every other Zoom pedal people ask about;
  MS-100BT works through third-party Bluetooth tools.

## 2026-10-09
- Docs: recovery button combo, "Before you start", MIDISTOMP and the
  Matujuice effects pack.
- README: the Four series (G1/B1/A1 Four) is ZD2 and not supported; related
  projects (MS StompCtrl).

## 2026-10-06
- **NAM + Cab Loader**: 16 capture and 16 cab slots, Eco mode, DSP meter.
- NAM beta: tester note, freeze recovery guide, report form.
- Patch Editor: opt-in experimental writes for MS-50G and MS-60B.

Earlier history: `git log`.
