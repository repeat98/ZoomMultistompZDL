"""Desktop reference renderer for Howl (v2) — feedback/resonant howl.

v1 fed a resonant filter back on itself and self-oscillated into constant
noise. v2 uses a tuned 2-pole resonator with a controllable pole radius r < 1:
unconditionally stable (decays to silence when idle, no constant noise), with
r near 1 giving a multi-second feedback howl. Input excites it; grit (soft
clip) sits outside the loop. Two detuned resonators (L/R) for stereo width.

Knobs (0..100): Tune, Annihil, Drive, Tone, Mix.
(Pedal build is 2-knob Tune+Annihil with Drive/Tone/Mix baked.)
"""

from __future__ import annotations

import numpy as np

GAP_MIN = 3.0e-5
GAP_MAX = 1.2e-3
GIN = 0.12


def _channel(mono, sr, fc, r, drive):
    w = 2.0 * np.pi * fc / sr
    a1 = 2.0 * r * np.cos(w)
    a2 = -r * r
    n = mono.shape[0]
    y = np.zeros(n)
    y1 = y2 = 0.0
    for i in range(n):
        yi = mono[i] * GIN + a1 * y1 + a2 * y2
        y2 = y1
        y1 = yi
        y[i] = yi
    s = y * drive
    # cubic soft-clip (outside the feedback loop), saturating to +/-1
    return np.where(np.abs(s) <= 1.0, 1.5 * s - 0.5 * s ** 3, np.sign(s))


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    tune = float(params.get("tune", 45.0)) / 100.0
    annih = float(params.get("annihil", 60.0)) / 100.0
    drive = 1.0 + float(params.get("drive", 55.0)) / 100.0 * 3.0
    tone = float(params.get("tone", 45.0)) / 100.0
    mix = float(params.get("mix", 70.0)) / 100.0

    fc = 80.0 + tune * 1870.0
    oma = 1.0 - annih
    r = 1.0 - (GAP_MIN + GAP_MAX * oma * oma)

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    tail_samps = int(tail * sr)
    mono = np.concatenate([mono, np.zeros(tail_samps)])

    wetL = _channel(mono, sr, fc, r, drive)
    wetR = _channel(mono, sr, fc * 1.012, r, drive)

    # simple output tone low-pass
    a = np.exp(-2.0 * np.pi * (400.0 + tone * 5000.0) / sr)
    for w in (wetL, wetR):
        lp = 0.0
        for i in range(len(w)):
            lp = (1.0 - a) * w[i] + a * lp
            w[i] = lp

    dry = np.concatenate([x, np.zeros((tail_samps, x.shape[1]))], axis=0)
    n = wetL.shape[0]
    out = np.empty((n, 2))
    out[:, 0] = dry[:, 0] * (1.0 - mix) + wetL * mix
    out[:, 1] = dry[:, min(1, dry.shape[1] - 1)] * (1.0 - mix) + wetR * mix
    return out
