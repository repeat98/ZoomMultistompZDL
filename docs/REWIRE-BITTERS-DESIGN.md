# Rewire / Bitters comparison and implementation proposal

Investigated 2026-09-24 at the user's request. Product behavior reference:
https://catalinbread.com/products/catalinbread-bitters

## Confirmed differences

Rewire currently runs five reorderable blocks: combined quantization/decimation,
drive, ring modulation, feedback comb, and single-sideband frequency shift.
It has no conventional sweeping phaser or delay-based pitch vibrato.

Catalinbread describes Bitters as distortion, a sine-swept phaser reaching 20 Hz,
and one selected processor: decimation, bitcrushing, frequency modulation
(described as pitch vibrato), or ring modulation. The chain can run forward or
backward. Zero on each amount bypasses its block; Mix spans dry to full wet.
The bitcrusher reaches one bit and includes a noise gate.

The public description does not specify the DSP equations, phaser stages,
feedback, filter frequencies, modulation ranges, quantizer convention, gate
envelope, or internal level calibration. Matching the documented structure is
feasible; an exact sonic clone is not established without reference recordings
or hardware comparisons.

## Proposed six controls

| Control | Function |
| --- | --- |
| Mode | Four fixed positions: Decim, Crush, FM, Ring |
| Amount | Amount/range for the selected processor; zero bypasses it |
| Drive | Distortion strength; zero bypasses it |
| Phase | Sine-sweep speed through 20 Hz; zero bypasses phaser |
| Order | Drive → Phase → selected processor, or the reverse |
| Mix | Original stereo dry blended with processed wet; 0 and 100 endpoints |

Use existing selector metadata for named choices and discrete positions in PE
and on the pedal. Six controls fit two pedal pages. Keep advanced DSP choices
internal instead of adding an extra page of parameters.

## DSP work

- Separate decimation from word-length reduction so either can be heard alone.
- Use a dedicated allpass phaser instead of the current comb block.
- Use fractional-delay pitch vibrato for FM; the existing frequency shifter
  adds Hz and is a different effect.
- Provide true stage bypass at zero, including removing permanent wet clipping
  and low-pass coloration when every stage is off.
- Gate only the crusher path and smooth transitions to/from its lowest bit
  depths; do not introduce a gate across all modes.
- Preserve independent L/R dry signals. Keep feedback bounded, flush tiny state,
  smooth continuous parameter changes, and fade discrete mode/order changes.
- Follow the repository's safe-DSP rules: per-instance arena state, no jump
  tables, unexpected helpers, or writable static DSP storage.

Exact tapers and phaser topology are implementation proposals, not claims about
Catalinbread's proprietary algorithm. Tune against independent listening tests.

## Rewire audit findings

`rw_drive(x, 0)` currently returns `rw_soft(x)`, not x. It has small-signal gain
1.5 and cubic coloration even at zero Drive. The final wet output also always
passes through `rw_soft` and a low-pass filter. Bits at zero still quantizes.
The current callback averages L/R before the dry/wet blend and writes that
same output to both channels, so Mix 0 does not preserve stereo dry audio.

## Compatibility decision

The user selected a separate effect, preserving Rewire. Implemented as **Tonic**,
FXID 499 / Delay, with the six controls above. See
[Tonic build and test notes](../src/custom/tonic/README.md). Its experimental
binary is in `dist/Tonic.ZDL`; hardware validation is pending. No Rewire DSP or
release binary was changed. NAMLite 0.09 remains available separately, and its
reported bitcrushed delayed output is recorded in the NAM investigation.

## Verification before a pedal build

Check exact stereo Mix 0, all-blocks-off unity, true full wet, each stage's zero
endpoint, audible differences between the two orders, all four mode ranges,
crusher silence/noise handling, finite bounded output, per-instance isolation,
mode-change transients, and arena guards. Inspect the TI object and linked ZDL
for safe sections, relocations and calls. Synchronize PE metadata and artwork
with the chosen controls. Hardware testing is still required after host checks.
