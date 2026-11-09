# Pedal research: which other Zoom pedals could run this project?

Started 2026-10-12, after the intro video brought in questions about other
Zoom pedals. This folder collects what is known per pedal family, where it came
from, and the next safe experiment. Facts marked *unverified* come from a single
community claim or our own inference.

**Short answer.** The original MultiStomps are close: the MS-100BT already runs
four of our effects, and a user runs NAM and CabIR on an MS-50G. The "+"
MultiStomps are the most promising new platform: same DSP family, unencrypted
effect files, and custom C effects already proven by another project. The
older G3/G5/B3 need firmware patching nobody has done.

## Tracker

| Pedal | Effect format | Install path | Our effects | Patch Editor | NAM | Next step |
|---|---|---|---|---|---|---|
| MS-70CDR | ZDL | Effect Manager | **working** | **working** | **working** | (home platform) |
| MS-50G | ZDL | Effect Manager | **NAM + CabIR confirmed** by a user ([#5](https://github.com/themanro/ZoomMultistompZDL/issues/5)) | **write test passed**; save, backup and restore worked | **working** (full rate and Eco); same headroom as MS-70CDR | Map the stock amps' CAB parameter ([#5](https://github.com/themanro/ZoomMultistompZDL/issues/5)) |
| MS-100BT | ZDL | Bluetooth only (third-party tools) | **4 confirmed** by a user | no (no USB MIDI) | untested | Ask [#4](https://github.com/themanro/ZoomMultistompZDL/issues/4) to try NAM + CabIR |
| MS-60B | ZDL | Effect Manager | untested on stock firmware; runs custom effects on MS-50G firmware | no: 105-byte, 4-slot patches | untested; flash space tight | Map the 105-byte layout; find an owner |
| G1on / G1Xon / B1on / B1Xon | ZDL | Effect Manager | one failure report upstream | no: different IDs, 5 slots | unknown DSP budget | First hardware report |
| MS-50G+ / MS-60B+ / MS-70CDR+ (and MS-200D+, MS-80IR+, MS-90LP+) | ZD2 | Handy Guitar Lab (iOS), community tools | not loadable (ZDL) | no: different protocol | needs a ZD2 port; NAM already runs there via [nam2zoom](https://github.com/freelender/nam-to-zoom) (50G+, 70CDR+; 60B+ experimental) | Build a pass-through ZD2 with the Stomphacks pipeline |
| G1 / G1X / B1 / B1X / A1 / A1X Four | ZD2 | Guitar Lab, Zoom Effect Manager 2.2+ | not loadable | no | needs a ZD2 port; less RAM | Read-only research only |
| G3n / G3Xn / G5n / B3n | ZD2 | Guitar Lab, Zoom Effect Manager 2.3+ | not loadable | no | needs a ZD2 port | Read-only research only |
| AC-2 / AC-3 | ZD2 | firmware updater only | not loadable | no (no screen) | unlikely | Out of scope for now |
| G6 / G11 / B6 | ZD2, possibly another platform | Guitar Lab | not loadable | no | unknown | Out of scope for now |
| G3 / G3X / G5 / B3 / A3 (originals) | none: effects compiled into firmware | none known | not loadable | no | would need firmware patching | Offline firmware analysis only |

## Priorities

1. **MS-50G**: effects, NAM and Patch Editor writes confirmed on firmware
   3.10 (#5), including knob edits; DSP headroom matches the MS-70CDR. Left:
   Patch Editor can't change stock amps' CAB setting yet.
2. **MS-100BT**: already runs our effects through
   [lopezchau's tools](https://github.com/lopezchau/zoom-ms100bt-bluetooth).
   Next: NAM and CabIR there, then a README update (it currently says "not
   supported").
3. **MS-60B**: needs the 105-byte patch layout in Patch Editor, and owners
   should know it has only about 10 free flash blocks (a NAM capture uses about 8).
4. **G1on family**: get the first identity line, patch dump and one install
   result. [repeat98#7](https://github.com/repeat98/ZoomMultistompZDL/issues/7)
   is the only report so far, and it's a failure.
5. **"+" MultiStomps (ZD2 port)**: the big one. Start from
   [Stomphacks](https://github.com/thammer/stomphacks) and port a pass-through,
   then one small effect, then NAM. Needs a "+" pedal on the desk.
6. **Four series and G3n/G5n/B3n**: wait for the "+" port; reuse what it learns.
7. **Original G3/G5/B3/A3**: long shot. Offline firmware analysis only.

## Files

- [zdl-family.md](zdl-family.md): MS-50G, MS-60B, MS-100BT, G1on, G1Xon, B1on, B1Xon
- [zd2-plus.md](zd2-plus.md): the "+" MultiStomps
- [zd2-other.md](zd2-other.md): Four series, G3n/G5n/B3n, AC-2/AC-3, G6/G11/B6
- [zfx4-originals.md](zfx4-originals.md): original G3, G3X, G5, B3, A3
- [demand.md](demand.md): who has asked, and what they reported
- [animated-covers.md](animated-covers.md): animating an effect's screen, and a live oscilloscope

Related: [PROBING-A-NEW-PEDAL.md](../PROBING-A-NEW-PEDAL.md) (safe checks for an
unknown pedal), [ZD2-PORT-NOTES.md](../ZD2-PORT-NOTES.md) (the port plan),
[STEREO-ROUTING.md](../STEREO-ROUTING.md).

## Ground rules for experiments

- Read-only first: identity request, patch dump, file listing.
- Confirm the pedal's recovery mode works **while it is healthy**, before
  writing anything.
- One small effect at a time, in a scratch patch, with a backup.
- Never interrupt a firmware update; close Effect Manager before running one.
