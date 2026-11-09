# The "+" MultiStomps: MS-50G+, MS-60B+, MS-70CDR+ (and MS-200D+, MS-80IR+, MS-90LP+)

The most promising new platform. Same DSP family as the originals (C674x),
effect files are plain code with a checksum, and custom C effects already run on
the MS-70CDR+ and MS-50G+ through [Stomphacks](https://github.com/thammer/stomphacks).
Our ZDL files can't load here; this needs a port.

Last researched 2026-10-12. See also [ZD2-PORT-NOTES.md](../ZD2-PORT-NOTES.md).

## Models

| Pedal | Released | ID (after family `6E 00`) |
|---|---|---|
| MS-50G+ | 2023 | 23 |
| MS-200D+ | Jan 2024 | 25 |
| MS-70CDR+ | May 2024 | 26 |
| MS-60B+ | 2024 | 27 |
| MS-80IR+ | Aug 2024 | 28 |
| MS-90LP+ | | 2B |

IDs from [thammer/zoom-explorer](https://github.com/thammer/zoom-explorer).

## The ZD2 file

- Starts with `ZDLF`; header has a CRC32, a **target bitfield** (which models
  may load it: `0x0080` = 50G+/60B+/70CDR+, `0x0100` = 200D+, `0x0200` = 80IR+),
  group, id, name. Sections: icon, description text, INFO (a `dspload` float),
  DATA (a plain TI C6000 ELF), parameter JSON.
- Not encrypted or compressed. Stomphacks rebuilds 147 of 149 stock MS-70CDR+
  files byte-exact ([zd2-format.md](https://github.com/thammer/stomphacks/blob/main/docs/zd2-format.md)).
- Installing also means adding the file to the on-device `FLST_SEQ.ZT2` list.

## What changes for our code

- **Blocks are 16 samples per channel**, not 8
  ([zd2-abi.md](https://github.com/thammer/stomphacks/blob/main/docs/zd2-abi.md)).
- Separate instance and context pointers; **delay memory (`instance[3]`) is
  undocumented**, which blocks reverbs, delays and NAM's history rings until
  someone maps it.
- DSP budget: `dspload` units, about **270** on the MS-70CDR+; the pedal refuses
  an effect past it. Ours would need re-measuring in those units.
- NAM: no Zoom pedal runs NAM officially (TONE3000's A2 launch lists other
  brands). A port looks plausible: same DSP family, more per-block work per call.

## Installing and editing

- Official: iOS Handy Guitar Lab apps. Zoom Effect Manager doesn't list the "+" models.
- Community: [mungewell/zoom-zt2](https://github.com/mungewell/zoom-zt2)
  (file transfer; Stomphacks needs its PR #112), [sym.bios.is](https://sym.bios.is/)
  (patch editor), [Zoom Explorer](https://github.com/thammer/zoom-explorer).
- SysEx: `F0 52 00 6E …`; patches via `45 00 00` / `46 00` (~989 bytes with
  CRC), files via `60 xx`. Different from our Patch Editor's protocol.

## Risk and recovery (sources disagree)

- Stomphacks' [SAFETY.md](https://github.com/thammer/stomphacks/blob/main/SAFETY.md)
  says there's no rescue boot mode. Its author bricked two MS-70CDR+ units
  during development ([zoom-zt2#93](https://github.com/mungewell/zoom-zt2/issues/93)).
- Later reports *(unverified)* describe an update mode: hold the **leftmost and
  rightmost knob buttons** while plugging in USB; a donor flash dump revived an
  MS-50G+ and an MS-60B+ ([#103](https://github.com/mungewell/zoom-zt2/issues/103),
  [#109](https://github.com/mungewell/zoom-zt2/issues/109)).
- Brick paths: crashing code saved into a patch; a half-written file or
  `FLST_SEQ` at reboot.

## First experiment (needs a "+" pedal)

1. MS-70CDR+ or MS-50G+ on firmware 1.20.
2. Read-only full backup, including `FLST_SEQ.ZT2`.
3. Check update-mode entry while the pedal is healthy.
4. Build Stomphacks' gain example; install into an unsaved scratch patch with
   autosave off; read back, compare, uninstall.
5. Then port one small effect from our pack with no delay memory. NAM last.
