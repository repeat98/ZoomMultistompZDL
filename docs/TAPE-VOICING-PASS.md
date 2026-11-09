# Oxide and Spool voicing pass — 2026-09-10

Built as version 1.01 with existing IDs, parameter order and storage layouts.
These are custom voicing changes, not claims of upstream Airwindows equivalence.

**Owner listening check passed 2026-09-10** as part of the rebuilt pack
("everything works good now"). That is a general in-use report rather than the
control-by-control comparison listed at the end of this document, so the specific
Input 50/75/100 and Feed 35..100 sweeps below are still the way to re-check the
voicing if either effect is changed again.

## Oxide

The active full kernel now compensates input drive above unity. The input law
still reaches 4x at Input 100, but wet output is multiplied by
`1 / (1 + 0.75 * (inputGain - 1))` above unity. Output remains independent,
0..2x, and Mix still blends against the original dry signal. Input 0..50 is
unchanged. Saturation still receives the full driven input; compensation happens
after the tape processing and before the existing output limiter.

New-patch defaults: Flutter 30 (was 50), HeadBmp 25 (was 50). This starts with
less pitch movement and bass resonance. Output metadata incorrectly described a
25..200 Hz control; it now describes gain. HeadBmp metadata now describes the
real resonance in the active full kernel, rather than the inactive fallback.

Host comparison used the actual full kernel with host pointers replacing only
firmware context decoding, initialized persistent state, a 441 Hz triangle at
0.2 peak, Flutter/HeadBmp zero, Output 50, Mix 100. Relative to Input 50:

| Input | Previous RMS increase | New RMS increase |
| --- | ---: | ---: |
| 50 | 0 dB | 0 dB |
| 75 | 6.90 dB | 1.15 dB |
| 100 | 11.52 dB | 1.28 dB |

This is signal-dependent compensation, not a loudness normalizer. High-level
input, Bias, Tilt and HeadBmp can still change perceived volume. The host test
is not a test of the Zoom ABI, CPU budget or live knob transitions.

## Spool

Feed now uses `n * (0.6 + 0.4*n) + 10 * max(n - 0.8, 0)^2`.
It is continuous with a continuous slope at 80. Representative loop coefficients:
0 -> 0, 35 -> 0.259, 50 -> 0.4, 80 -> 0.736, 90 -> 0.964, 100 -> 1.4.
Previously it reached only 0.92 at maximum despite the manifest promising 1.4.
The last portion is now an experimental sustained-feedback range. Actual
oscillation onset depends on the tape filter, Wear, Drive and signal spectrum;
a coefficient over one alone does not establish sustained oscillation.

New-patch Mix is 35 (was 50); its fallback is also 0.35, fixing the previous
manifest mismatch (UI 50 versus fallback 0.4). Feed remains 35 by default.
No changes to transport modulation, delay allocation or the spring tank.

## Validation and listening order

- Both TI builds: zero object relocations, zero .fardata, no new externals.
- Release init/metadata verification passes for the whole 22-effect pack.
- Three new host tests: monotonic control curves and endpoints, actual Oxide
  full-kernel level comparison, and Spool's real sample processor with ten-second
  impulse tails at Feed 80/100 and Wear 0/100. All tails remain finite and bounded;
  Feed 80 tails decay. These tests do not prove how musical the result sounds.
- PE database regenerated from the binaries, including new defaults.

Install Oxide and Spool from dist and close Effect Manager. With PE disconnected,
compare Oxide Input 50/75/100 at Output 50, then check Input 0, Mix 0 and bypass.
Try Spool Feed 35/50/80/90/100, starting at low monitor volume for the top range.
Check saved settings after patch changes and power cycling. Existing patches
retain their stored knob positions but the new drive/feedback laws change their
sound. Defaults change only when creating/replacing an effect. Hard-refresh PE
before adding either effect so its defaults match the binaries.
