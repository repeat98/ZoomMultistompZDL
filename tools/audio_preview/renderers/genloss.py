"""Desktop reference renderer for GenLoss — tape/VHS generation-loss
degradation (Chase Bliss Generation Loss / Shallow Water vibe).

Chain:
  saturation -> wow & flutter (modulated fractional delay) -> bandwidth loss
  (sub roll-off + low-pass) -> random dropouts/warble -> + hiss -> mix

  - Wow/flutter: a slow LFO + a faster LFO + a filtered random walk modulate
    a fractional read delay, warbling the pitch like an unstable tape motor.
  - Bandwidth: a gentle high-pass (tape has no deep sub) plus a low-pass whose
    cutoff follows Tone.
  - Dropouts: random short amplitude dips (worn/damaged tape), scaled by Wobble.
  - Hiss: shaped white noise at the Hiss level.

Knobs (0..100): Wow, Tone, Hiss, Drive, Wobble, Mix.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter

TWO_PI = 6.28318530717959


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    wow = float(params.get("wow", 45.0)) / 100.0
    tone = float(params.get("tone", 40.0)) / 100.0
    hiss = float(params.get("hiss", 30.0)) / 100.0
    drive = float(params.get("drive", 45.0)) / 100.0
    wobble = float(params.get("wobble", 35.0)) / 100.0
    mix = float(params.get("mix", 100.0)) / 100.0

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    n = mono.shape[0]
    t = np.arange(n) / sr
    rng = np.random.default_rng(2024)

    # 1. Tape saturation.
    sat = np.tanh(mono * (1.0 + drive * 4.0)) / (1.0 + drive * 0.8)

    # 2. Wow & flutter: modulate a fractional read delay.
    wow_amp = wow * 0.0040 * sr          # slow wow up to ~4 ms
    flut_amp = wow * 0.0009 * sr         # fast flutter, shallower
    rw = np.cumsum(rng.standard_normal(n))
    rw = lfilter(*butter(2, 2.0 / (sr * 0.5)), rw)   # ~2 Hz random walk
    rw = rw / (np.max(np.abs(rw)) + 1e-9) * wobble * 0.0035 * sr
    base = 0.012 * sr
    mod = base + wow_amp * np.sin(TWO_PI * 0.7 * t) + flut_amp * np.sin(TWO_PI * 8.0 * t) + rw
    readpos = np.arange(n) - mod
    warbled = np.interp(readpos, np.arange(n), sat)

    # 3. Bandwidth loss: high-pass sub + low-pass following Tone.
    warbled = lfilter(*butter(1, 70.0 / (sr * 0.5), btype="high"), warbled)
    cutoff = 1200.0 * (2.0 ** (tone * 3.0))          # ~1.2k .. ~9.6k Hz
    cutoff = min(cutoff, sr * 0.45)
    warbled = lfilter(*butter(2, cutoff / (sr * 0.5)), warbled)

    # 4. Dropouts / warble: random short amplitude dips.
    gain = np.ones(n)
    if wobble > 0.0:
        n_dips = int(wobble * (n / sr) * 5.0)
        for _ in range(n_dips):
            pos = int(rng.random() * n)
            length = int((0.02 + rng.random() * 0.06) * sr)
            depth = 0.4 + rng.random() * 0.6 * wobble
            end = min(pos + length, n)
            w = np.hanning(end - pos) if end > pos else np.array([])
            gain[pos:end] -= depth * w
        gain = np.clip(gain, 0.0, 1.0)
    warbled *= gain

    # 5. Hiss: shaped white noise.
    if hiss > 0.0:
        noise = rng.standard_normal(n)
        noise = lfilter(*butter(1, 6000.0 / (sr * 0.5)), noise)
        warbled = warbled + noise * hiss * 0.06

    out = np.empty((n, 2))
    sd = int(0.004 * sr)
    warbledR = np.concatenate([np.zeros(sd), warbled[:-sd]]) if sd < n else warbled
    out[:, 0] = x[:, 0] * (1.0 - mix) + warbled * mix
    out[:, 1] = x[:, min(1, x.shape[1] - 1)] * (1.0 - mix) + warbledR * mix
    return out
