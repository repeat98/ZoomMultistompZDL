# Original G3, G3X, G5, B3, A3 (ZFX-IV era)

Same DSP family as the MultiStomps on paper, but **effects are compiled into the
main firmware**, not loaded as separate files. There's no known way to add an
effect without patching Zoom's firmware image, and nobody has done that publicly.

Last researched 2026-10-12.

## What's known

| Pedal | Released | Last firmware | SysEx ID | Editing |
|---|---|---|---|---|
| G3 | May 2011 | 2.10 (2013) | 0x5A | Edit&Share |
| G3X | 2011 | 2.10 | 0x59 | Edit&Share |
| G5 | Feb 2012 | 1.20 | 0x5B | Edit&Share |
| B3 | ~2011 | | 0x4F *(one community script)* | |
| A3 | ~2012 | | not found | |

- Zoom calls the DSP "ZFX-IV, 32-bit floating point"
  ([2015 catalogue](https://zoomrussia.ru/manuals/FX_Catalog_E.pdf)). No public
  chip markings; a reverse engineer says Zoom built this firmware with TI's
  tools and the core code looks like ZDL code
  ([Zoom-Firmware-Editor#2](https://github.com/Barsik-Barbosik/Zoom-Firmware-Editor/issues/2)),
  so a TI C6000-family chip is likely.
- [Zoom Firmware Editor](https://github.com/Barsik-Barbosik/Zoom-Firmware-Editor)
  lists the G3, G5 and B3 as unsupported: no usual file table, effect data
  scattered in smaller pieces.
- A G5 owner found parameter descriptors in the updater but nothing like a ZDL,
  and no way to inject effects ([zoom-zt2#4](https://github.com/mungewell/zoom-zt2/issues/4),
  [ZoomPedalFun/G5](https://github.com/shooking/ZoomPedalFun/tree/master/G5)).
- The G3's 2.00 update added amps and 6-effect chains by reflashing the whole
  firmware, so diffing G3 1.12 against 2.00 would show where effects live.
- The firmware editor's README lists "G3X" under ZD2; issue #20 shows the G3X
  updater is rejected as invalid, so that's almost certainly a typo for G3Xn.
- G3 update mode: hold both PATCH SELECT keys while connecting USB
  *(unverified, from a mirrored readme)*.

## What support would take

1. Find the effect list, parameter descriptors and DSP dispatch inside the
   firmware image (symbols are stripped).
2. Find free RAM and DSP headroom.
3. Patch all three for each new effect, and build a modified updater with a
   recovery path.

## Safe first experiments (offline)

1. Unpack the G5 1.20 and G3 1.12/2.00/2.10 updaters; look for a TI boot image
   header (`TIPA`, as on the MS-100BT), ELF magic, or a file table.
2. Diff G3 1.12 vs 2.00 to locate the added amp code and its descriptors.
3. Take an effect both the G5 and MS-70CDR have; disassemble the MS-70CDR ZDL
   and search the G5 image for matching instruction sequences.
4. Read-only on hardware: identity request, then a file-listing request to see
   whether a file system exists at all.
