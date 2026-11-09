# Mode selector audit — 2026-09-14

Audited the active build manifests and DSP of all 22 release effects. Older
unused manifests describe Klang Mode and Corrupt Harm; neither exists in the
current releases. These must not become controls in PE.

| Effect | Control | Named choices |
|---|---|---|
| Rooms | Mode | Room, Digit, Peak, Gate, Wave, Gong |
| Spool | Div | 1/16, 1/8T, 1/8, dotted 1/8, 1/4, dotted 1/4 |
| Hydra | Div | Grain, 1/32, 1/16T, 1/16, 1/8T, 1/8, dotted 1/8, 1/4 |
| Spiral | Div | 1/32, 1/16T, 1/16, 1/8T, 1/8, dotted 1/8, 1/4, dotted 1/4 |
| Rewire | Route | BDRCS, SCRDB, DSBCR, RCSBD, SBRDC |
| Stasis | Capture | Stomp, Release, Hold |
| Stock RndmFLTR | Type / Chara | HPF, BPF, LPF / 2Pole, 4Pole |

Rewire route letters: Bits, Drive, Ring, Comb, Shift. `T` means triplet;
trailing `.` means dotted. Hydra's manifest comment incorrectly calls default
42 an eighth-note triplet: the actual DSP puts it in 1/16. The editor now shows
the actual DSP interpretation, without changing the default.

The other 16 custom releases have no pure mode selectors: Oxide, Galactic,
Flower, Shatter, Arrakis, Microlm, Corrupt, Klang, GenLoss, Scorch, Howl, Taffy,
Dissolve, Mangle, Dustbox, Gyre. Integer/sample quantization is not itself a
mode. In particular Rewire Bits also varies sample hold continuously; Mangle
Crush combines quantization and decimation; pitch/rise/span controls remain
continuous. Those retain continuous controls.

## PE implementation

`build/selector_metadata.py` records exhaustive raw ranges from active DSP,
including float32 UI*0.01 boundary behavior. Rewire's first route includes raw
20 (the float32 result is below the source's 0.20f threshold). Metadata is
attached when rebuilding the effect DB, including the inline PE copy.

Named dropdowns and fixed dial positions replace continuous controls for
these audited selectors. Binary Chara uses a wider lever. Hardware readback
only changes the display: it never rounds a saved value or sends an edit.
Selecting a different mode sends a representative value inside its existing
range. Mouse, keyboard, wheel and controller paths retain the existing MIDI
edit/apply policy. Numeric range and patch IDs are unchanged.

`tools/selector_preview.html` is an offline snapshot using the actual PE
selector functions. It does not connect to MIDI.

## Pedal evidence and pilot

`stock_zdls/MS-70CDR_RNDMFLTR.ZDL` has GetString callbacks in descriptor +0x24:
Type points to 0xaa4 and Chara to 0xaf8. Disassembly shows A4 is raw integer,
B4 destination buffer, return value is character count. Its eight-byte string
slots encode HPF/BPF/LPF and 2Pole/4Pole. The supplied hardware photo confirms
those labels and the binary switch appearance.

The linker can now attach object-defined `ZDL_GetLabel_<index>` callbacks at
that field with relocations. Opt-in generated C callbacks copy at most seven
ASCII characters plus NUL. Six experimental builds are in
`build/selector-pilot/`; the regular dist releases do not contain these
callbacks. Build with:

```
ZDL_SELECTOR_LABELS=1 ZDL_SELECTOR_OUTPUT_DIR="$PWD/build/selector-pilot" python3 build_all.py stasis rooms tapeecho4 hydra spiral rewire
```

Pilot scope: dynamic mode names on the pedal, preserving existing raw ranges.
This is NOT yet a hardware-verified change. It also does not turn a 0–100
pedal control into a six-position selector: matching that rotation behavior
requires a separate raw-range/edit-handler design and saved-patch migration.
The cover bitmap is separate from the firmware's edit-page controls; changing
cover artwork cannot implement that switch behavior.

Start hardware validation with pilot Rooms.ZDL. Open Mode, confirm the six
names across its range, verify the other parameters still display normally,
then switch patches and reload. Check the same sound/mode survives. If display
fails, restore dist/Rooms.ZDL. Only promote the callbacks after hardware
confirmation. No hardware connection or writes were performed by this task.

## Validation

- 19 PE tests pass, including no-write readback, same-mode preservation,
  blocked edits, selector changes and controller release behavior.
- Host-compiled generated label callbacks tested at every valid raw value,
  with returned length and buffer sentinel checks.
- All six pilot descriptor callback addresses/relocations and initialization
  bodies verified; their parsed patch ABI equals the regular releases.
- All 22 regular release initialization/manifest/DB checks pass.
- Browser preview tested by selecting Rooms Gong; displayed label and raw92
  agree with metadata. No real pedal rendering claim is made.

## Hardware follow-up: broken label display and Rooms6

User tested pilot Rooms on 2026-09-14: PE worked, but the pedal Mode retained
0–100 and rendered corrupt/off-screen text. The range was an acknowledged
limitation of the first pilot; the text was a bug.

Root cause found: `_apply_relocs` patched object-code ABS_L16/H16 references
at build time but omitted them from `.rela.dyn`. The new label callbacks load
string addresses in .const, so these addresses also need runtime relocation.
The linker now emits those records; validation checks both low/high dynamic
relocations for every label, not just the descriptor callback address.
All six label pilots have been rebuilt with this correction. They still need
hardware retesting. Regular dist files were not rebuilt in this follow-up.

`build/probes/Rooms6.ZDL` is a separate six-position test, effect ID 490/group8
(patch ID 1079247632, checked free in the current effect database). Mode max=5;
the isolated ROOMS_DISCRETE_MODE DSP path converts the shared handler's
raw/100 input to mode0–5. It includes the corrected label callbacks. The
normal Rooms ID and its 0–100 decoding remain unchanged. Host tests exercise
the actual conditional DSP snippet for all old and new raw values.

Build: `python3 src/custom/rooms/build.py --discrete-mode-pilot`.
Refresh the database afterward with `python3 build/extract_effect_db.py`.
The generated header should be regenerated normally after a pilot build
before committing it (normal builds do this automatically).

Hardware test: install Rooms6 alongside Rooms, add Rooms6 in a spare patch,
and turn Mode through its six positions. Expected labels: Room, Digit, Peak,
Gate, Wave, Gong. Check Time/Freq and patch reload as well. In PE, enable
Show probes under Developer diagnostics to choose Rooms6. Existing Rooms
patches stay on the old effect; no silent conversion is attempted.

### Label fit and PE styling follow-up

User confirms dial behavior works, but the seven-character Release value and
Capture heading overrun the pedal column. Pilot Stasis now uses Capt as the
pedal heading and Stmp / Rels / Hold as values. PE retains Capture and full
mode names. Generated pedal mode values are limited to five ASCII characters.
All label pilots and Rooms6 were rebuilt; normal dist remains unchanged.

PE selector circles, fill, stroke and pointers now match continuous knobs;
tick marks still identify the actual discrete positions. Borderless native
selects retain keyboard access, with mode text aligned to the numeric-value
row and a chevron. Browser appearance checked; callback and PE tests pass.

### Release promotion

After the user confirmed the shortened Stasis display, dynamic short labels
were enabled by default for all six existing custom selectors. Release
headings are now at most five characters, with full PE names restored by an
effect-specific alias table. See EFFECT-DISPLAY-REFRESH.md for the all-22
graphics pass and the remaining raw-range compatibility distinction.
