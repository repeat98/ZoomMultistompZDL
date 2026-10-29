# fxid Registry

`fxid` is the 16-bit effect identity baked into every ZDL (header bytes
64–65, little-endian; the `gid` is byte 60). Two effects with the same `fxid`
and the same `gid` are treated as the same effect by the Zoom firmware and by
Zoom Effect Manager, which shows the pair as one index, `0xGG00FFFF` (for
example `0x08000199` = gid 8, fxid 409). A duplicate can cause silent
overwrite, a freeze on load, or worse (see the incident below).

The ID space is shared with every other ZDL collection, not just this repo.
A pedal can hold effects from several collections at once.

## Rules

- **Before claiming an ID, check it against
  [IDs used by other collections](#ids-used-by-other-collections) as well as
  this repo's own tables.** An ID is free only if no row in either uses the
  same `gid` + `fxid`. Prefer an ID that no collection uses in any `gid`.
  Re-check the other collections when you claim it: they keep adding effects.
- Stock effects use fxid **0 – 384** in most groups, but Zoom's own effects
  go higher in Drive (gid 3, up to 528), Modulation (gid 6, up to 512) and
  Reverb (gid 9, up to 448); see the stock rows below. Never use a stock ID.
- Community/custom effects use fxid **400 – 999**. Modwerk's Zoom pedal page
  treats gid 8, fxid 403 – 957 as "added effects".
- Diagnostic/hardware-probe effects share the 400–999 space but are never
  loaded alongside release effects, so probe collisions are low-risk during
  development. Keep them out of `dist/` and avoid reusing a release fxid for
  a probe.
- Never reuse a retired release ID (see the release table); old patches and
  pedals still refer to it.
- The linker emits a warning for fxid ≤ 384 (reserved range).
- If two effects collide (same `fxid` AND same `gid`), whether both are ours
  or one is from another collection, fix ours before shipping.
- `python3 -B build/fxid_check.py` checks every release manifest and its
  `dist/` header against this file: no duplicates among our release effects,
  no clash with the rows under "IDs used by other collections", and every
  release ID listed in the release table. `build_all.py` runs it after a full
  release build, and `tests/test_fxid_registry.py` runs it as a test.

## Incident: TEcho4.ZDL and Spool.ZDL shared 0x08000199 (issue #8)

Until 2026-10-29, `TEcho4.ZDL` (TapeEcho4) shipped as gid 8, fxid 409, the
same ID as `Spool.ZDL` in
[themanro/ZoomMultistompZDL](https://github.com/themanro/ZoomMultistompZDL).
Spool is that fork's renamed descendant of TapeEcho4 (same source directory)
and kept the ID. Zoom Effect Manager flagged `repeating index effect -
0x08000199`. A user unchecked Spool, checked TEcho4 and wrote the pedal
(MS-70CDR, firmware 2.10): it stuck at the boot logo, then stopped
responding after official firmware updater attempts, and was only recovered
by reflashing its ROM chip with a CH341A programmer. The exact failure
mechanism is not proven, but duplicate IDs are now treated as unsafe.

This registry then tracked only this repo's own effects, so the clash was
invisible here. TapeEcho4 moved to fxid **946** (`0x080003B2`), and the
section "IDs used by other collections" was added.

## gid → category mapping

| gid | Category |
|-----|----------|
| 1   | Dynamics |
| 2   | Filter   |
| 3   | Drive    |
| 4   | Amp      |
| 5   | Cab      |
| 6   | Modulation |
| 7   | SFX / Special |
| 8   | Delay    |
| 9   | Reverb   |

## Current registry

### Release effects

| fxid | gid | effect_name | File | Notes |
|------|-----|-------------|------|-------|
| 400 | 2 | GAIN | `src/airwindows/gain` | Minimal smoke-test / template |
| 401 | 2 | PurestDr | `src/airwindows/purestdrive` | |
| 402 | 2 | TapeHack | `src/airwindows/tapehack` | |
| 403 | 3 | ToTape9 | `src/airwindows/totape9` | Drive category; install a stock Drive effect too |
| 404 | 6 | StChorus | `src/airwindows/stereochorus` | |
| 405 | 9 | VerbTiny | `src/airwindows/verbtiny` | Hardware unverified |
| 406 | 7 | ToVinyl4 | `src/airwindows/tovinyl4` | Diagnostic; not in dist/ |
| 408 | 9 | Galactic | `src/airwindows/galactic` | Hardware unverified |
| 946 | 8 | TapeEcho4 | `src/airwindows/tapeecho4` | Ships as TEcho4.ZDL. Was 409 until 2026-10-29 (issue #8) |
| 410 | 1 | OTT | `src/custom/ott` | Hardware unverified |

Retired: **409 / gid 8** (TapeEcho4 until 2026-10-29). Spool.ZDL uses it;
never reuse it.

### Hardware probe effects (not in dist/)

These share the fxid space during development. Several have intentional
collisions because only one probe variant is loaded at a time — but
note the warnings below.

| fxid | gid | effect_name | File | Collision warning |
|------|-----|-------------|------|-------------------|
| 400 | 2 | HELLO | `src/airwindows/hello` | Collides with GAIN (same fxid+gid); never load both |
| 405 | 2 | CtxMap | `src/hardware_probes/ctxmap` | Different gid from VerbTiny; still avoid loading together |
| 406 | 2 | ParamTap | `src/hardware_probes/paramtap` | Different gid from ToVinyl4 |
| 407 | 2 | CtxGate | `src/hardware_probes/ctxgate` | **Same fxid+gid as InitProbe** |
| 407 | 2 | InitProbe | `src/hardware_probes/initprobe` | **Same fxid+gid as CtxGate** |
| 408 | 2 | CtxNib | `src/hardware_probes/ctxnib` | Different gid from Galactic |
| 409–412 | 2 | StatePing (+ variants) | `src/hardware_probes/stateping` | Different gid from Spool (8/409) |
| 410 | 2 | SyncProbe | `src/hardware_probes/syncprobe` | Different gid from OTT |
| 413 | 2 | StateIso | `src/hardware_probes/stateiso` | |
| 414 | 2 | SyncPrV2 | `src/hardware_probes/syncprobv2` | |
| 415 | 2 | BpmHunt | `src/hardware_probes/bpmhunt` | **Same fxid+gid as StateComb** |
| 415 | 2 | StateComb | `src/hardware_probes/statecomb` | **Same fxid+gid as BpmHunt** |
| 416 | 2 | DescComb | `src/hardware_probes/desccomb` | **Same fxid+gid as SyncCalc + SyncPrV3** |
| 416 | 2 | SyncCalc | `src/hardware_probes/synccalc` | **Same fxid+gid as DescComb + SyncPrV3** |
| 416 | 2 | SyncPrV3 | `src/hardware_probes/syncprobv3` | **Same fxid+gid as DescComb + SyncCalc** |
| 417–425, 427–444 | 2 | Dsz512K (+ size variants) | `src/hardware_probes/descsize` | |
| 426 | 2 | DescIso | `src/hardware_probes/desciso` | |

## IDs used by other collections

Checked 2026-10-29 by reading the header bytes (gid at 60, fxid at 64–65)
of each collection's published ZDLs, plus their manifests and ID notes for
IDs that are generated or not yet in a release. No third-party file is
stored in this repo. Ranges are inclusive. `build/fxid_check.py` reads this
table, so keep one `gid` per row and only numbers, commas and ranges in the
`fxid` column.

| gid | fxid | Effects | Source |
|-----|------|---------|--------|
| 8 | 403, 408, 409, 414–416, 440, 449–452, 454–459, 461, 463, 465–468, 470, 472, 473, 484, 490, 499 | Oxide, Galactic, **Spool**, Scope, Ring, Skull, Stasis, Spiral, Microlm, Flower, Shatter, Corrupt, Klang, GenLoss, Scorch, Howl, Hydra, Dissolve, Dustbox, Rewire, Taffy, Loop, Spectrum, Mangle, Rooms, Arrakis, Gyre, Scrub/Rooms6, Tonic | themanro/ZoomMultistompZDL @ 71f4582, `dist/*.ZDL`, `build/selector-pilot/*.ZDL` |
| 8 | 402, 404, 405, 410–413, 443, 496, 498, 908–913, 920–922, 929 | TapeHack, Lush, Room, OTT, Redraw, CoverRW, Blink, Reel, MatProb, NAMLite and NAM/CabIR probes (source only, not in its `dist/`) | themanro/ZoomMultistompZDL @ 71f4582, `src/*/*/manifest*.json`, `tools/effects_db.json` (`probes`) |
| 8 | 453, 460, 462, 464, 469, 471, 474–483 | Old IDs of renamed effects, still on pedals and in patches | themanro/ZoomMultistompZDL @ 71f4582, `tools/effects_db.json` (`legacy`) |
| 8 | 500–699, 900–907, 950–957 | NAMLite capture slots 1–216 (generated in the browser) | themanro/ZoomMultistompZDL @ 71f4582, `tools/effects_db.json` (`generated`), `tools/slot_identity.js` |
| 8 | 700–899, 930–945 | CabIR slots 1–216 (generated in the browser) | themanro/ZoomMultistompZDL @ 71f4582, `tools/effects_db.json` (`generated`), `tools/slot_identity.js` |
| 2 | 441, 442, 444–446, 453, 458, 460, 462, 464, 497 | CtxNib, StatePing, CtxMap, ParamTap, CtxGate, SyncProbe, Howl, StateComb, SyncPrV3, HELLO, NAMTest (probes renumbered there, older builds) | themanro/ZoomMultistompZDL @ 71f4582, `src/*/*/manifest*.json` |
| 3 | 454, 457 | Corrupt, Scorch (older builds) | themanro/ZoomMultistompZDL @ 71f4582, `src/custom/*/manifest.json` |
| 6 | 451, 453, 455, 456 | Flower, Arrakis, Klang, GenLoss (older builds) | themanro/ZoomMultistompZDL @ 71f4582, `src/custom/*/manifest.json` |
| 7 | 447, 448 | CtxWatch, EdgeWatch (probes) | themanro/ZoomMultistompZDL @ 71f4582, `src/hardware_probes/*/manifest.json` |
| 8 | 480, 485–497 | DualShft, DubSiren, Choral, WaveFold, EuGate, S.GN_L, Scrub, DirtBox, (492 dropped effect), Breather, SyncEQ, GridDly, Sweep, Looper (MIDISTOMP 2.0) | matujuice/zoom-ms-zdl-effects-pack @ 5d30e70, `dist/*.ZDL`, release v1.5 `SyncEQ.ZDL`, `src/custom/*/manifest_pedal.json`; also bundled in themanro's `dist/` |
| 8 | 498, 499 | DryPrb, TempoPrb (probes) | matujuice/zoom-ms-zdl-effects-pack @ 5d30e70, `src/probes/*/manifest_pedal.json` |
| 2 | 552, 554–556, 565–569 | IRDUAL4, MS1960VS, M1960VT1, M1960VT2, HYBRIDIR, MS1960, GJ_IR, TRUCAB, TRUCAB2 | Leemuzhko/Zoom-ZDL-FX @ 85a490f, `zdl/filter/**/*.ZDL` (same in release v0.3.1) |
| 3 | 580, 581 | NAMPLEX, NAM5150 | Leemuzhko/Zoom-ZDL-FX @ 85a490f, `zdl/drive/nam/*/*.ZDL` |
| 4 | 337–340, 351, 370 | ENGL, ENGL2, CABSIM, PLEXI, JCM800, PLEXI2 (modified stock amps) | Leemuzhko/Zoom-ZDL-FX @ 85a490f, `zdl/guitar-amp/modified-amps/*/*.ZDL` |
| 7 | 915 | SYNX2 | Leemuzhko/Zoom-ZDL-FX @ 85a490f, `zdl/sfx/synthesis/SYNX2/SYNX2.ZDL` |
| 11 | 13311 | LM_DINO | Leemuzhko/Zoom-ZDL-FX @ 85a490f, `zdl/pedal-operated/games/LM_DINO/LM_DINO.ZDL` |
| 7 | 520 | DrumBox | Barsik-Barbosik/Custom-Zoom-ZDL-Effects @ be45bf9, `dist/DrumBox.ZDL` (same in release v1.0.1) |
| 8 | 505 | SilverSt | marcfuentes/silverst-zdl @ 801b689, `SilverSt.ZDL` |
| 2 | 497, 753 | RTFM, Div0 (modding examples) | ELynx/zoom-fx-compressed @ 8798fb9, `files/effects/*.ZDL` |
| 3 | 400, 416, 432, 448, 464, 496, 528 | Zoom stock: OCTFUZZ, BGGRID, RED_CRU, TB_MK15, SWEETDRV, RCBOOST, DYNDRIVE | ELynx/zoom-fx-compressed @ 8798fb9, `files/effects/*.ZDL` |
| 6 | 400, 416, 432, 448, 464, 480, 496, 512 | Zoom stock: CLONECHO, STONEPHA, BF_FLG_2, SILKYCHO, MIRAGECH, CRN_CHO, ANA234CH, CRN_TRI | ELynx/zoom-fx-compressed @ 8798fb9; themanro `tools/effects_db.json` (`stock`) |
| 9 | 400, 416, 432, 448 | Zoom stock: PARTICLE, SPC_HOLE, MNGLD_SP, DUAL_REV | ELynx/zoom-fx-compressed @ 8798fb9; themanro `tools/effects_db.json` (`stock`) |

Not in the table: stock IDs up to 384 (covered by the rule above); the
copies of this repo's own effects that themanro's fork still carries under
their original IDs (GAIN 2/400, PurestDr 2/401, ToVinyl4 7/406 and the
gid 2 probes 407–444), which are the same effects; and
collections that publish no ZDLs with fixed IDs: Senty3kat's Vocowder, XDuck
and sForm repositories (README only), zisonzishen0415-stack/nam-forge (writes
themanro's NAM slot IDs) and freelender/nam-to-zoom (ZD2 pedals).

Reserved, beyond the IDs above: themanro's README reserves gid 8 fxid
403–499 for its pack, 500–699 and 900–907, 950–957 for NAM captures, and
700–899 and 930–945 for cabs, and asks other projects to avoid them. In
403–957 only 908–929 and 946–949 fall outside those reservations, and its
probes use some of 908–929. TapeEcho4 now takes 946.

## Next available fxid for a new release effect

Checked 2026-10-29: **947 – 949** in gid 8 are unused by this repo and every
collection above, in every gid. Elsewhere in 403–957 the space is used or
reserved by themanro's pack; agree an ID with that project before taking one
from its reserved ranges.

When you claim a new fxid, add it to this table in the same PR that adds the
`manifest.json`.
