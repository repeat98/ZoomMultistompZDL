# ZDL family: MS-50G, MS-60B, MS-100BT, G1on, G1Xon, B1on, B1Xon

Same effect format as the MS-70CDR (`.ZDL`, a TI C6000 ELF), so our effects can
in principle load as-is. The differences are in installation, patch layout,
chain length, flash space and DSP budget.

Last researched 2026-10-12.

## At a glance

| Pedal | Released | Latest firmware | SysEx ID | Slots | Patch dump | Install | Custom effects seen |
|---|---|---|---|---|---|---|---|
| MS-70CDR | ~2013 *(unverified)* | 2.10 | 0x61 | 6 | 146 B | Effect Manager | ours (home) |
| MS-50G | 2012 | 3.10 | 0x58 | 6 | 146 B | Effect Manager | **NAM (full rate + Eco) and CabIR** |
| MS-60B | 2013 | 2.10 | 0x5F | 4 | 105 B | Effect Manager | Matujuice pack, on MS-50G firmware |
| MS-100BT | 2012 | 1.30 | 0x5E | 6 | 140 B + CRC (Bluetooth) | Bluetooth tools only | **Shatter, Galactic, Microloom, Spool**, WaveFold, DubSiren |
| G1on | 2013 | 1.21 | 0x63 | 5 | ~102 B *(inferred)* | Effect Manager, firmware editor | one failure report |
| G1Xon | 2013 | 1.21 | 0x64 | 5 | as G1on | as G1on | none |
| B1on | 2014 | 1.30 | 0x65 | 5 | 134 B | as G1on | none |
| B1Xon | 2014 | | 0x66 *(unverified)* | 5 | | Effect Manager | none |

Sources: device IDs from [g200kg/zoom-ms-utility](https://github.com/g200kg/zoom-ms-utility/blob/master/midimessage.md),
[SysExTones/g1on](https://github.com/SysExTones/g1on/blob/master/g1on/CONSTANTS.py),
[shooking/ZoomPedalFun](https://github.com/shooking/ZoomPedalFun),
[zoom-zt2#24](https://github.com/mungewell/zoom-zt2/issues/24); MS-family slots and
flash from [MIDISTOMP models/](https://github.com/matujuice/zoom-ms-midistomp/tree/main/models).

## Shared platform (MS-50G / MS-60B / MS-70CDR)

- The bootloader is byte-identical on all three; the OS is one codebase built
  per model ([MIDISTOMP docs/formats.md](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/formats.md)).
- Updater parts: 256 KiB bootloader, 704 KiB OS, 12 KiB boot logo, 2.8 MiB
  effects file system. No checksum or signature on the OS or bootloader.
- Free 4 KiB flash blocks: MS-50G 300, MS-70CDR 17, **MS-60B 10**.
- Update mode: hold **Up + Down** while plugging in USB. Zoom's own updater
  also rewrites the bootloader; MIDISTOMP's builds skip that step
  ([flashing.md](https://github.com/matujuice/zoom-ms-midistomp/blob/main/docs/flashing.md)).
- Stock effects are only partly shared byte-for-byte. Across the 830 stock
  ZDLs in [repeat98's corpus](https://github.com/repeat98/ZoomMultistompZDL/tree/main/stock_zdls):
  MS-50G vs MS-70CDR 58 of 71 identical, MS-60B vs MS-70CDR 73 of 108, G1on vs
  MS-70CDR 35 of 60, G1on vs G1Xon 101 of 101.

## MS-50G

- **Status:** **NAM at full rate, NAM Eco and CabIR work** on an MS-50G with
  firmware 3.10 (identity `f0 7e 00 06 02 52 58 00 00 00 33 2e 31 30 f7`;
  [#5](https://github.com/themanro/ZoomMultistompZDL/issues/5), 2026-10-13).
  Patch dumps decode with our MS-70CDR layout
  ([#1](https://github.com/themanro/ZoomMultistompZDL/issues/1)).
- **Patch Editor writes:** the opt-in write test **passed** on the same pedal
  (146/146 bytes identical, 2026-10-14); saving a patch and backing up and
  restoring all 50 banks worked, and knob edits are heard on the pedal.
- **DSP:** same as the MS-70CDR. Patch Editor's meter read 85% for NAM alone
  and 89% for NAM + cab, both clean; adding a chorus or the stock Delay was
  fine (an earlier crackle turned out to be the audio interface clipping).
- **Graphic EQ** (`0x200004`) was missing from our database: its band names
  use the pedal's "Hz" glyph (byte `0x1F`), which the DB builder rejected.
  Fixed; all GEQ variants now load.
- **Bug: stock amps' CAB knob can't move in Patch Editor.** In Zoom's amp
  files the CAB parameter has no maximum; its default is a packed effect
  reference (e.g. `0x04000140`, group 4 / ID 320). The real range isn't in the
  amp file. Needs two patch dumps from an MS-50G with the cab changed on the
  pedal.
- **Next:** the amp CAB dumps.

## MS-60B

- **Patch Editor:** 105-byte, 4-slot patches. Our "Enable writes" test can't
  pass on it (it expects 146 bytes) and stays read-only, which is safe but
  misleading. Needs its own layout map.
- **Flash:** only 10 free blocks; remove stock effects before adding any. A NAM
  capture (~30 KB) takes about 8.
- **Effects:** the Matujuice pack runs on an MS-60B **cross-flashed to MS-50G
  3.10**. On that setup a 36 KB ZDL hung at boot and 30.9 KB booted
  ([pack SAFE-DSP-RULES](https://github.com/matujuice/zoom-ms-zdl-effects-pack)).
  Untested on the stock 2.10 OS.
- Guitar amp effects need `CMN_DRV.ZDL` on bass pedals.
- **Next:** find an owner on stock firmware; map the 105-byte layout.

## MS-100BT

- **Effects work.** [lopezchau/zoom-ms100bt-bluetooth](https://github.com/lopezchau/zoom-ms100bt-bluetooth)
  reports Shatter, Galactic, Microloom and Spool from this repo running, plus
  Matujuice's WaveFold and DubSiren
  ([#4](https://github.com/themanro/ZoomMultistompZDL/issues/4)).
  Single source, created 2026-10-08.
- **Install:** Bluetooth only. lopezchau's MS-100BT Manager (macOS),
  [ms-stompctrl](https://github.com/1njected/ms-stompctrl) (Chrome, Web Serial
  over Bluetooth). New effects must also be added to `FLST_SEQ.ZDT`.
- **Limits:** about 200 files on the file system; bass categories never show,
  and listing an effect under the wrong category froze the pedal. Per-effect
  memory area about 680–689 KB (enough for NAM's ~86 KB working set).
- **Recovery:** the updater runs over Bluetooth; no USB recovery combo found.
  "All Initialize" (hold knob 1 at power-on) restores factory patches.
- **Patch Editor:** can't reach it without USB MIDI; would need Web Serial over
  Bluetooth like ms-stompctrl.
- **Next:** NAM + CabIR test by the #4 reporter; list it as "works with
  third-party tools" in the README.

## G1on, G1Xon, B1on, B1Xon

- **Effects:** ZDL, and [Zoom Firmware Editor](https://github.com/Barsik-Barbosik/Zoom-Firmware-Editor)
  says effects cross-load between these and the MultiStomps. Zoom Effect
  Manager lists them.
- **Only report:** [repeat98#7](https://github.com/repeat98/ZoomMultistompZDL/issues/7),
  where a custom ZDL and upstream's PureStDr failed on a G1on while other
  plugins worked. No details yet.
- **Unknowns:** DSP budget, per-effect memory area, 5-slot patch format, how
  the updater treats the bootloader.
- [Leemuzhko/Zoom-ZDL-FX](https://github.com/Leemuzhko/Zoom-ZDL-FX) targets
  this model, untested on all listed pedals.
- **Next:** identity line + patch dump + one small install; then measure the
  memory area (lopezchau's `effects/memprobe` does this).
