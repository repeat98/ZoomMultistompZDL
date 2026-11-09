"""Desktop reference renderer for Flower — a Korg Toneworks "Random" style
sample-and-hold step filter (the Deftones "Digital Bath" sound).

The Korg Pandora "Random" effect is a sample-and-hold filter modulation: a
resonant filter whose cutoff jumps to a new RANDOM value on every step at a
set Rate, held until the next step. Run as two independent L/R sequences it
becomes a "stereo random filter" (Korg shipped exactly that), which gives the
glitchy, glassy, formant-jumping width heard in Digital Bath's middle eight.

DSP per channel:
  - A sample-and-hold LFO picks a new random cutoff every `step` samples.
  - Optional one-pole glide (Smooth) between steps: 0 = hard glitch steps,
    high = liquid sweeps.
  - A TPT (zero-delay-feedback) state-variable filter provides a clean,
    stable resonant lowpass whose resonance peak tracks the random cutoff.

Knobs (manifest order, 0..100):
  Rate   step speed, ~0.5..14 Hz
  Range  random sweep span in octaves, 0..3.5
  Manual center frequency, ~100..2000 Hz (log)
  Reso   resonance / peak sharpness
  Smooth step glide (0 glitchy .. high liquid)
  Mix    dry/wet

Desktop uses real tan(); a pedal port would swap it for an approximation.
"""

from __future__ import annotations

import numpy as np

PI = 3.14159265358979


def _channel(x, sr, rate_hz, center_hz, range_oct, q, smooth_ms, seed):
    n = x.shape[0]
    out = np.zeros(n)

    step = max(int(sr / max(rate_hz, 0.01)), 1)
    k = 1.0 / max(q, 0.5)            # SVF damping; lower = more resonance
    rng = np.random.default_rng(seed)

    # Smoothing coefficient for the cutoff glide (one-pole).
    if smooth_ms <= 0.1:
        coef = 1.0                   # instant jump -> hard steps
    else:
        tau = smooth_ms * 0.001 * sr
        coef = 1.0 - np.exp(-1.0 / tau)

    # SVF state.
    ic1 = 0.0
    ic2 = 0.0

    cutoff = center_hz
    target = center_hz
    nyq = sr * 0.45
    counter = 0
    for i in range(n):
        if counter <= 0:
            # New random cutoff: center * 2^(uniform(-range/2, +range/2)).
            r = rng.random() - 0.5
            target = center_hz * (2.0 ** (r * range_oct))
            if target < 40.0:
                target = 40.0
            elif target > nyq:
                target = nyq
            counter = step
        counter -= 1

        cutoff += coef * (target - cutoff)

        # TPT state-variable filter, lowpass output.
        g = np.tan(PI * cutoff / sr)
        a1 = 1.0 / (1.0 + g * (g + k))
        a2 = g * a1
        a3 = g * a2
        v3 = x[i] - ic2
        v1 = a1 * ic1 + a2 * v3        # bandpass
        v2 = ic2 + a2 * ic1 + a3 * v3  # lowpass
        ic1 = 2.0 * v1 - ic1
        ic2 = 2.0 * v2 - ic2
        # Lowpass for body + bandpass to expose the moving resonant peak (the
        # vocal/formant "random filter" character).
        out[i] = v2 + 0.9 * v1
    return out


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    rate_hz = 0.5 + float(params.get("rate", 45.0)) / 100.0 * 13.5
    range_oct = float(params.get("range", 70.0)) / 100.0 * 3.5
    manual = float(params.get("manual", 45.0)) / 100.0
    center_hz = 100.0 * (2.0 ** (manual * 4.32))     # ~100..2000 Hz log
    q = 0.7 + float(params.get("reso", 75.0)) / 100.0 * 11.3   # Q 0.7..12
    smooth_ms = float(params.get("smooth", 15.0)) / 100.0 * 60.0
    mix = float(params.get("mix", 85.0)) / 100.0

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)

    # Independent random sequences L/R -> stereo random filter.
    wetL = _channel(mono, sr, rate_hz, center_hz, range_oct, q, smooth_ms, seed=11)
    wetR = _channel(mono, sr, rate_hz, center_hz, range_oct, q, smooth_ms, seed=29)

    # Resonance can boost at the peak; soft-limit and apply a little makeup.
    wetL = np.tanh(wetL * 1.1)
    wetR = np.tanh(wetR * 1.1)

    out = np.empty((x.shape[0], 2))
    dryL = x[:, 0]
    dryR = x[:, min(1, x.shape[1] - 1)]
    out[:, 0] = dryL * (1.0 - mix) + wetL * mix
    out[:, 1] = dryR * (1.0 - mix) + wetR * mix
    return out
