# Custom Effect Pack (themanro)

A curated **library of 22 effects** for the Zoom MS-70CDR (ZDL family),
built on the [repeat98/ZoomMultistompZDL](https://github.com/repeat98/ZoomMultistompZDL)
toolchain. Eighteen are originals (most with a full-quality Python **desktop
preview** in `tools/audio_preview/renderers/`); the rest are rebuilt/renamed
Airwindows-derived ports plus one contributed effect (Dustbox). All are grouped
under the **Delay** category with a custom on-device cover, and all have rebuilt release binaries in `dist/`.

> **Updated September 14, 2026:** all 22 effects have individual laboratory-style
> graphics, LCD proportion corrections, and short pedal labels. Saved effect IDs
> and parameter ranges are preserved. See [display notes](docs/EFFECT-DISPLAY-REFRESH.md).

### Every effect ends with Mix

Levels across the pack used to be inconsistent, and the naming was most of the
reason. Galactic called it DryWet, Howl and Scorch called it Level, Oxide called
it Output, and GenLoss had no level control at all. Worse, the ones called Level
or Output were not crossfades: Howl's only scaled a wet send to a 0.45 ceiling,
and Scorch's was an output gain topping out at 0.5×, so Scorch could never reach
unity however far it was turned.

Now every effect ends with a real dry/wet **Mix**, default 50 — except Dustbox,
whose fourth knob is Power. Stasis uses a true Mix while a capture is held and
passes dry stereo unchanged when idle; its sixth control selects stomp or
explicit capture.

Effects that saturate lift RMS regardless of input, so a few carry a named wet
trim (`SC_WET_TRIM`, `TOTAPE9_WET_TRIM`, `GL_WET_TRIM`) applied before the
crossfade. Those are by-ear calibration points, not derived constants.

### Known gaps

* The desktop Python renderers are alternate listening references. Their extra
  controls and algorithms can differ from the reduced pedal versions; they are
  not evidence that a feature exists in the shipped ZDL.
* Some features are deferred on the originals (Klang's frequency-shifter modes,
  GenLoss dropouts, Scorch's full cab IR). Compare each effect's `manifest.json`
  against its `manifest_pedal.json` to see what was cut for the pedal build.
* Knobs 4 and beyond use edit handlers synthesised by the build rather than stock
  ones. These are now confirmed working in all six slots, including at patch load
  — see [docs/RELEASE-INIT-AUDIT.md](docs/RELEASE-INIT-AUDIT.md). Editing them
  live over MIDI is still limited to slots 1–3 by the firmware; the patch editor
  handles 4–6 for you ([docs/MIDI-PARAM-EDIT.md](docs/MIDI-PARAM-EDIT.md)).

## Sound previews

### Experimental addition: Tonic

[Tonic](src/custom/tonic/README.md) is a separate Bitters-inspired effect with
distortion, a phaser, four selectable processors (Decim, Crush, FM, Ring), and
forward/reverse routing. It has its own PE controls, pedal graphic, and Effect
Manager thumbnail. `dist/Tonic.ZDL` is available for local testing; hardware
validation is pending, so it is not yet part of the 22-effect release pack.
Rewire and its saved-patch controls are unchanged.

### Release pack samples

All **22 effects now have samples**. Open a WAV link to play or download it.
These are desktop renders, **not recordings from the pedal**.

### Existing desktop references

The original 11 files below were checked for readable WAV data, finite samples,
non-silence, and full-scale clipping on September 14. They pass those checks and
are retained unchanged. Their original presets were not saved, and they use the
older Python algorithms rather than the current release C kernels. The checks
are technical validation, not a fresh listening review or a pedal comparison.
Most were peak-normalized, so these files should not be used to compare effect
loudness.

| Effect | Demo | Dry source |
|---|---|---|
| Microloom | [microloom.wav](previews/audio/microloom.wav) — lush shimmer wash | [chord](previews/audio/dry_chord.wav) |
| Flower | [flower.wav](previews/audio/flower.wav) — Digital Bath random filter | [chord](previews/audio/dry_chord.wav) |
| Shatter | [shatter.wav](previews/audio/shatter.wav) — machine-gun stutter | [drums](previews/audio/dry_drums.wav) |
| Arrakis | [arrakis.wav](previews/audio/arrakis.wav) — −2 oct beating drone | [drone](previews/audio/dry_drone.wav) |
| Corrupt | [corrupt.wav](previews/audio/corrupt.wav) — PLL square synth | [guitar](previews/audio/dry_guitar.wav) |
| Klang | [klang.wav](previews/audio/klang.wav) — metallic ring mod | [chord](previews/audio/dry_chord.wav) |
| GenLoss | [genloss.wav](previews/audio/genloss.wav) — wrecked tape | [chord](previews/audio/dry_chord.wav) |
| Scorch | [scorch.wav](previews/audio/scorch.wav) — djent high-gain amp+cab | [riff](previews/audio/dry_riff.wav) |
| Howl | [howl.wav](previews/audio/howl.wav) — self-oscillating feedback | [guitar](previews/audio/dry_guitar.wav) |
| Hydra | [hydra.wav](previews/audio/hydra.wav) — double-time ghost + half-time drag | [drums](previews/audio/dry_drums.wav) |
| Spiral | [spiral.wav](previews/audio/spiral.wav) — slow 8-second rising delay | [guitar](previews/audio/dry_guitar.wav) |

### New release-source references

These 11 samples run the current release C audio code on the desktop at 44.1 kHz.
Only the firmware pointer plumbing is replaced with host-owned buffers. This
checks the audio algorithm, but does not emulate the pedal CPU, loader, MIDI,
or converters. Each starts from the release manifest defaults. Stasis changes
Capture from Release to Hold at 1.5 seconds so its freeze can be heard.

The dry source is fed at **25% amplitude** to leave headroom. Outputs are not
loudness-matched; a peak-only safety reduction is applied if needed. Five seconds
of tail and a final 100 ms fade are included. The dry links below are the original,
unattenuated files, so turn them down for a level comparison.

| Effect | Sample | Dry source |
|---|---|---|
| Spool | [Tape echo](previews/audio/spool.wav) | [guitar](previews/audio/dry_guitar.wav) |
| Oxide | [Tape coloration](previews/audio/oxide.wav) | [chord](previews/audio/dry_chord.wav) |
| Galactic | [Large modulated reverb](previews/audio/galactic.wav) | [chord](previews/audio/dry_chord.wav) |
| Taffy | [Variable-speed playback](previews/audio/taffy.wav) | [guitar](previews/audio/dry_guitar.wav) |
| Dissolve | [Smear and glitch](previews/audio/dissolve.wav) | [drums](previews/audio/dry_drums.wav) |
| Mangle | [Delay at default settings](previews/audio/mangle.wav) | [drums](previews/audio/dry_drums.wav) |
| Rooms | [Room mode reverb](previews/audio/rooms.wav) | [chord](previews/audio/dry_chord.wav) |
| Rewire | [Lo-fi processing chain](previews/audio/rewire.wav) | [guitar](previews/audio/dry_guitar.wav) |
| Dustbox | [Motor-like fuzz](previews/audio/dustbox.wav) | [riff](previews/audio/dry_riff.wav) |
| Stasis | [Capture at 1.5 s, then sustain](previews/audio/stasis.wav) | [chord](previews/audio/dry_chord.wav) |
| Gyre | [Grain capture](previews/audio/gyre.wav) | [guitar](previews/audio/dry_guitar.wav) |

[Exact settings and source hashes](previews/audio/release_samples.json) make the
new renders reproducible. [Audio check report](previews/audio/validation.json)
lists sample rate, duration, peaks, RMS and clipping checks for every WAV.

After building the release pack (which generates its parameter headers), run:

```bash
python3 tools/audio_preview/render_release_samples.py
python3 tools/audio_preview/check_samples.py
```

The renderer requires a host C compiler, NumPy and SoundFile. Existing Python
reference demos can be explored separately with the tool below.

## Hearing them on desktop (no compiler, no pedal)

The Python renderers provide alternate desktop versions for auditioning:

```bash
pip install numpy scipy soundfile
python3 tools/audio_preview/make_test_signal.py input.wav        # or make_drum_loop.py
python3 tools/audio_preview/preview.py render scorch input.wav out.wav --set gain=85
python3 tools/audio_preview/preview.py list                      # all effects + coverage
```

## Building the pedal `.ZDL`

Requires the TI C6000 compiler (see the main README). The build scripts here
point `TI_ROOT` at `/Applications/ti/ti-cgt-c6000_8.5.0.LTS` — edit if yours
differs.

```bash
python3 build_all.py flower          # one effect -> dist/Flower.ZDL
python3 build_all.py scorch          # etc.
```

Pre-built `.ZDL` files for all 22 are in [`dist/`](dist/).

## Implementation notes

All pedal builds follow the repo's safe-DSP rules: no math library (polynomial
sines, cubic soft-clips, reciprocal approximations, baked filter coefficients),
no runtime divide, persistent state in the `ctx[3]` arena, the `ctx[11]/ctx[12]`
magic shuttle preserved, and controlled persistent memory. Audio kernels avoid unsupported relocation
patterns; dynamic parameter-label callbacks use verified runtime relocations.
See [release verification](docs/RELEASE-INIT-AUDIT.md).

Licensing follows the parent repo (MIT for repo code).
