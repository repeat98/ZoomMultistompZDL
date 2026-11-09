# Other ZD2 pedals: Four series, G3n/G5n/B3n, AC-2/AC-3, G6/G11/B6

All use Zoom's newer ZD2 effect format, so nothing in this repo loads on them.
None has a custom-code pipeline yet. Wait for the "+" MultiStomp port
([zd2-plus.md](zd2-plus.md)) and reuse what it learns.

Last researched 2026-10-12.

## G1 / G1X / B1 / B1X / A1 / A1X Four

- **Released:** G1/G1X Four Jan 2019; A1/A1X Four Aug–Oct 2019; B1/B1X Four 2019.
- **Hardware:** one shared board; TMS320C6745 (C674x) DSP; 4 MB SPI flash
  ([w1ne/zoom-g1four](https://github.com/w1ne/zoom-g1four)). Model bytes `0C`,
  `0D`, `0E`, `0F` for G1, G1X, B1, B1X Four.
- **Less memory:** delays are capped at 3 s ("3S" effect variants).
  `GUARDZDL.ZT2` lists the full-size effects that must not load on this
  hardware ([zoom-zt2](https://github.com/mungewell/zoom-zt2)).
- **Effects aren't interchangeable** with the "+" models: different IDs and
  groups ([zoom-zt2#87](https://github.com/mungewell/zoom-zt2/issues/87)).
- **Install:** Guitar Lab; third-party
  [Zoom Effect Manager](https://zoomeffectmanager.com/en/download/) 2.2.0+ (all
  six models), 2.3.1+ writes in normal mode.
- **Custom code:** stock effects disassembled and reassembled ran on a G1 Four
  (2025, [zoom-zt2#93](https://github.com/mungewell/zoom-zt2/issues/93)). No C
  toolchain yet.
- **Update mode:** hold both footswitches while plugging in USB (w1ne). A G1X
  Four bricked during an update remains unresolved
  ([#109](https://github.com/mungewell/zoom-zt2/issues/109)).
- **NAM:** least likely of the ZD2 group, given the reduced memory.

## G3n / G3Xn / G5n / B3n

- **Released:** G5n 2016, G3n/G3Xn Oct 2016, B3n about 2017.
- Many effect binaries are shared with the G1 Four; A1 Four effects fail on a G3n
  ([zoom-zt2#66](https://github.com/mungewell/zoom-zt2/issues/66)). Chip unknown.
- **Install:** Guitar Lab; Zoom Effect Manager 2.3.0+ (G5n from 2.3.2);
  Zoom Firmware Editor supports all four.
- **Risk:** a G5n lost button functions after a bad `FLST_SEQ`
  ([#108](https://github.com/mungewell/zoom-zt2/issues/108)).
- No custom-code demonstration found.

## AC-2 / AC-3

- ZD2-like effects, all in one group, no screen. Firmware updater only. No custom work found.

## G6 / G11 / B6

- ZD2 (their own target bit). Reported to have about 3× the DSP power of
  earlier models, and the B6 runs at 88.2 kHz *(unverified)*. Chip unknown, so
  possibly a different platform. G11 cabinets load on a G1X Four; G11 amps
  don't ([zoom-zt2#26](https://github.com/mungewell/zoom-zt2/issues/26)).
