"""Desktop reference renderer for the StereoChorus pedal DSP.

Mirrors stereochorus.c (an Airwindows StereoChorus port) — the first
ctx[3]-backed effect and the one confirmed running on MS-70CDR hardware.

Faithful pieces:
  - Speed/Depth control laws: speed = (0.32 + A/6)^10 per sample,
    depth = B / 60 / speed (clamped to 3000 samples).
  - Per-channel modulated delay line with the source's 3-tap fractional
    interpolation and the L/R sweep phase offset (pi/2.7 vs pi) that gives
    the stereo spread.
  - The Airwindows "air" highpass pre-emphasis (airFactor/even/odd).

Simplifications vs the pedal build:
  - Float delay line instead of the fixed-point int8388352 quantization
    (the pedal uses ints only because of its runtime; math is equivalent).
  - The cycle/lastRef undersampling ring is skipped: on the pedal `cycle`
    is always 1, so every sample is processed anyway.
  - Real sin() instead of the pedal approximation.

Note: at the manifest defaults (Speed=0, Depth=0) the depth is ~0 and the
output is essentially dry. Drive the knobs (e.g. --set speed=40 --set
depth=55) to hear the chorus.
"""

from __future__ import annotations

import numpy as np

TWO_PI = 6.28318530718
GCOUNT_TOP = 32760
BUFFER = GCOUNT_TOP * 2 + 8192  # mirror region + headroom for max offset


def _process_channel(col, sweep0, speed, depth):
    n = col.shape[0]
    out = np.empty(n, dtype=np.float64)
    buf = np.zeros(BUFFER, dtype=np.float64)

    sweep = sweep0
    gcount = GCOUNT_TOP
    air_prev = air_even = air_odd = 0.0
    flip = False

    for i in range(n):
        x = col[i]

        # Airwindows "air" pre-emphasis.
        air_factor = air_prev - x
        if flip:
            air_even += air_factor
            air_odd -= air_factor
            air_factor = air_even
        else:
            air_odd += air_factor
            air_even -= air_factor
            air_factor = air_odd
        air_odd = (air_odd - ((air_odd - air_even) * 0.00390625)) * 0.99990001
        air_even = (air_even - ((air_even - air_odd) * 0.00390625)) * 0.99990001
        air_prev = x
        x += air_factor
        flip = not flip

        if gcount < 1 or gcount > GCOUNT_TOP:
            gcount = GCOUNT_TOP
        count = gcount
        buf[count + GCOUNT_TOP] = buf[count] = x

        offset = depth + (depth * np.sin(sweep))
        whole = int(offset)
        frac = offset - whole
        r = count + whole
        val = buf[r] * (1.0 - frac) + buf[r + 1] + buf[r + 2] * frac
        val -= ((buf[r] - buf[r + 1]) - (buf[r + 1] - buf[r + 2])) * 0.02
        out[i] = val * 0.5  # 3-tap sum carries ~2x weight

        sweep += speed
        if sweep > TWO_PI:
            sweep -= TWO_PI
        gcount -= 1

    return out


def render(audio, sample_rate, params, tail, root):
    A = float(np.clip(float(params.get("speed", 0.0)) / 100.0, 0.0, 1.0))
    B = float(np.clip(float(params.get("depth", 0.0)) / 100.0, 0.0, 1.0))

    speed = (0.32 + A * (1.0 / 6.0)) ** 10
    depth = B * (1.0 / 60.0) / speed
    if depth > 3000.0:
        depth = 3000.0

    x = audio.astype(np.float64)
    # Ensure stereo so the L/R sweep offset is audible.
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)

    out = np.empty_like(x)
    sweeps = [1.16355283466, 3.14159265359]  # pi/2.7, pi
    for ch in range(x.shape[1]):
        out[:, ch] = _process_channel(x[:, ch], sweeps[ch % 2], speed, depth)
    return out
