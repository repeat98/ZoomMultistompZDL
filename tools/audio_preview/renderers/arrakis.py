"""Desktop reference renderer for Arrakis — a Dune-style detuned sub-octave
drone.

The input is pitched down one or two octaves (granular 2-tap pitch shift) and
split into TWO voices whose detune is swept in OPPOSITE directions by a slow
LFO. The two low voices beat against each other, and because the detune
wanders back and forth the beat rate speeds up and slows down — the
"two low oscillators tuning against each other" sound. Saturation and a
low-pass filter add the massive weight.

Knobs (manifest order, 0..100):
  Pitch  sub-octave depth (0 unison, 50 = -1 oct, 100 = -2 oct)
  Detune voice spread in cents (the beat amount)
  Sweep  LFO rate of the detune wander (~0.02..0.6 Hz)
  Drive  saturation / weight
  Tone   low-pass cutoff
  Mix    dry/wet
"""

from __future__ import annotations

import numpy as np

PI = 3.14159265358979
TWO_PI = 6.28318530717959


def _read(buf, pos, n):
    if pos < 0.0:
        return 0.0
    i0 = int(pos)
    if i0 + 1 >= n:
        return 0.0
    frac = pos - i0
    return buf[i0] * (1.0 - frac) + buf[i0 + 1] * frac


def _pitch_voice(mono, sr, ratio_arr, grain_len):
    """2-tap granular pitch shift with a per-sample (slowly varying) ratio."""
    n = mono.shape[0]
    out = np.zeros(n)
    half = max(grain_len // 2, 1)
    inv_half = 1.0 / half
    p = 0.0
    for i in range(n):
        d1 = p
        d2 = (p + half) % grain_len
        e1 = (half - abs(half - d1)) * inv_half
        e2 = (half - abs(half - d2)) * inv_half
        out[i] = _read(mono, i - d1, n) * e1 + _read(mono, i - d2, n) * e2
        p += (1.0 - ratio_arr[i])
        if p >= grain_len:
            p -= grain_len
        elif p < 0:
            p += grain_len
    return out


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    pitch = float(params.get("pitch", 50.0)) / 100.0
    detune = float(params.get("detune", 45.0)) / 100.0
    sweep = float(params.get("sweep", 35.0)) / 100.0
    drive = float(params.get("drive", 55.0)) / 100.0
    tone = float(params.get("tone", 40.0)) / 100.0
    mix = float(params.get("mix", 80.0)) / 100.0

    semitones = -24.0 * pitch                         # 0 .. -2 octaves
    base_ratio = 2.0 ** (semitones / 12.0)
    cents = detune * 50.0                             # up to +/-50 cents
    sweep_hz = 0.02 + sweep * 0.58                    # ~0.02 .. 0.6 Hz
    grain_len = int(0.09 * sr)                        # ~90ms grains (good for lows)

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    tail_samps = int(tail * sr)
    mono = np.concatenate([mono, np.zeros(tail_samps)])
    n = mono.shape[0]
    t = np.arange(n) / sr

    # Two voices, detune swept in opposite directions -> beating that wanders.
    lfo = np.sin(TWO_PI * sweep_hz * t)
    ratio_a = base_ratio * (2.0 ** (+cents * lfo / 1200.0))
    ratio_b = base_ratio * (2.0 ** (-cents * lfo / 1200.0))
    va = _pitch_voice(mono, sr, ratio_a, grain_len)
    vb = _pitch_voice(mono, sr, ratio_b, grain_len)
    wet = 0.5 * (va + vb)

    # Saturation for weight/growl.
    wet = np.tanh(wet * (1.0 + drive * 4.0)) * (1.0 / (1.0 + drive * 1.5))

    # One-pole low-pass (Tone). Dark by default for the massive feel.
    cutoff = 120.0 * (2.0 ** (tone * 5.0))            # ~120 .. ~3800 Hz
    a = np.exp(-TWO_PI * cutoff / sr)
    lp = 0.0
    for i in range(n):
        lp = (1.0 - a) * wet[i] + a * lp
        wet[i] = lp

    # Slight stereo width: tiny inter-voice delay split L/R.
    sd = int(0.013 * sr)
    wetR = np.concatenate([np.zeros(sd), wet[:-sd]]) if sd < n else wet

    dry = np.concatenate([x, np.zeros((tail_samps, x.shape[1]))], axis=0)
    out = np.empty((n, 2))
    out[:, 0] = dry[:, 0] * (1.0 - mix) + wet * mix
    out[:, 1] = dry[:, min(1, dry.shape[1] - 1)] * (1.0 - mix) + wetR * mix
    return out
