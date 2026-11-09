# Effect display refresh — 2026-09-14

The confirmed Stasis short-label treatment now ships in the regular release
builds. The six custom selectors (Rooms Mode; Spool, Hydra and Spiral Div;
Rewire Route; Stasis Capture) have dynamic, short pedal labels. PE retains full
names and its matching dial/borderless mode-value controls.

All hardware parameter headings are limited to five characters. Effect-specific
aliases in `build/parameter_display.py` translate those headings back to full
PE names without changing parameter order, values, defaults or edit symbols.
Examples: Capt, Len, Flutr, FlSpd, HBump, Brght, Repl, Feed, Trem, Chnce.

The existing raw ranges and effect IDs remain intact. Therefore the 0–100
mode/division controls still have that range on the pedal; named display is
now included, while PE selects modes by detents. Rooms6 remains a separate
0–5 test effect. No saved patches are silently reinterpreted or migrated.

## Native graphics

All 22 releases now have individual native-pixel artwork. The Stasis, Spool
and Rooms designs continue the approved pilot; the other 19 use dedicated
layouts in `src/airwindows/common/pack_covers.py`. Their circular motifs are
compensated for the approximate 1.4 LCD pixel aspect. Controls retain their
existing firmware overlay coordinates. Bitmap files are 128×64 monochrome;
the gallery and PE show physical LCD proportions without decorative noise.

- Galactic: orbit and stars; Arrakis: dunes and sun.
- Flower: flower; Microlm: woven grid; Oxide: tape strip.
- Shatter: fractured letters; Corrupt: displaced signal lines.
- Klang: interlocking rings; GenLoss: cassette deck.
- Scorch: lightning; Howl: concentric speaker rings.
- Taffy: stretched wrapper; Dissolve: letters breaking into particles.
- Mangle: opposing teeth; Hydra: three branching paths.
- Rewire: routed traces; Dustbox: speckled enclosure.
- Spiral: winding spiral; Gyre: circulating wave pattern.

Previous gallery images are preserved under
`graphics/effect-cover-explorations/pre-pack-gallery/` (and the earlier pilot
originals directory). The full contact sheet and browser gallery are in
`graphics/effect-cover-explorations/full-pack/`. They are decoded from dist
binaries, not generated at higher resolution.

Build with the explicit release names in build_all.py. Then run:

```
python3 build/make_gallery_png.py
python3 build/make_pack_preview.py
python3 build/verify_release_init.py
python3 build/verify_release_displays.py
```

Firmware label relocations, short headings, image dimensions, unique bitmaps,
overlay bounds, patch metadata and initialization are checked. The new 19
covers still need a physical pedal review; no simulated live values are used
in the gallery. This change does not intentionally alter DSP behavior.

Validation completed: 22/22 initialization checks and 22/22 display checks;
13 host tests and 19 PE tests pass. The final decoded contact sheet was
visually reviewed after rebuilding. Verification output is saved in
RELEASE-INIT-VERIFICATION.json and RELEASE-DISPLAY-VERIFICATION.json.

## Laboratory artwork pass

A second pass takes cues from the ivory console cover: phase/uncertainty
symbols, short Cyrillic instrument stamps, calibration scales, numbered
terminals, broken connections and mounting marks. Seven designs use a light
instrument-panel field. Details are deliberately placed; no random noise or
high-resolution texture is added. Control labels and live-value areas remain
unchanged. Native circle compensation is retained.

The detailing layer is `src/airwindows/common/lab_details.py`. The previous
contact sheet is preserved in
`graphics/effect-cover-explorations/before-lab-pass/contact-sheet.png`.
The current full-pack sheet remains decoded from the release ZDLs.
