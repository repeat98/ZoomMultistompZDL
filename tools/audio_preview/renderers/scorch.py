"""Desktop reference renderer for Scorch — aggressive high-gain amp + cab.

Chain:
  pre high-pass (tighten) -> input gain -> stage 1 asymmetric soft clip
  -> interstage low-pass -> stage 2 clip -> stage 3 clip
  -> tone stack (Bass low-shelf, Mid peak, Treble high-shelf, Presence peak)
  -> 4x12-style cab IR (short FIR convolution) -> output level + safety clip

The cab is a synthesized short impulse response (high-pass + speaker low-pass
+ presence/thump resonances), the same shape that ports to a baked C FIR.

Knobs (0..100): Gain, Bass, Mid, Treble, Presence, Level.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter, fftconvolve


def _peaking(fs, f0, q, db):
    a_ = 10.0 ** (db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / (2.0 * q)
    b = [1 + alpha * a_, -2 * cw, 1 - alpha * a_]
    a = [1 + alpha / a_, -2 * cw, 1 - alpha / a_]
    return [c / a[0] for c in b], [1.0, a[1] / a[0], a[2] / a[0]]


def _shelf(fs, f0, db, high):
    a_ = 10.0 ** (db / 40.0)
    w0 = 2.0 * np.pi * f0 / fs
    cw, sw = np.cos(w0), np.sin(w0)
    alpha = sw / 2.0 * np.sqrt((a_ + 1.0 / a_) * (1.0 / 0.9 - 1.0) + 2.0)
    tsa = 2.0 * np.sqrt(a_) * alpha
    s = 1.0 if high else -1.0
    b0 = a_ * ((a_ + 1) + s * (a_ - 1) * cw + tsa)
    b1 = -2 * a_ * s * ((a_ - 1) + s * (a_ + 1) * cw)
    b2 = a_ * ((a_ + 1) + s * (a_ - 1) * cw - tsa)
    a0 = (a_ + 1) - s * (a_ - 1) * cw + tsa
    a1 = 2 * s * ((a_ - 1) - s * (a_ + 1) * cw)
    a2 = (a_ + 1) - s * (a_ - 1) * cw - tsa
    return [b0 / a0, b1 / a0, b2 / a0], [1.0, a1 / a0, a2 / a0]


def _cab_ir(fs, taps=512):
    imp = np.zeros(taps)
    imp[0] = 1.0
    y = lfilter(*butter(2, 85.0 / (fs * 0.5), btype="high"), imp)
    y = lfilter(*butter(4, 5200.0 / (fs * 0.5), btype="low"), y)
    pres = lfilter(*butter(2, [2200.0 / (fs * 0.5), 3800.0 / (fs * 0.5)], btype="band"), imp)
    thump = lfilter(*butter(2, [85.0 / (fs * 0.5), 150.0 / (fs * 0.5)], btype="band"), imp)
    ir = y + 0.5 * pres + 0.45 * thump
    ir = ir[:taps]
    fade = taps // 4
    ir[-fade:] *= np.linspace(1.0, 0.0, fade)
    ir /= np.sqrt(np.sum(ir * ir)) + 1e-9
    return ir


def render(audio, sample_rate, params, tail, root):
    fs = sample_rate
    gain = float(params.get("gain", 70.0)) / 100.0
    bass = float(params.get("bass", 55.0)) / 100.0
    mid = float(params.get("mid", 30.0)) / 100.0
    treble = float(params.get("treble", 60.0)) / 100.0
    presence = float(params.get("presence", 65.0)) / 100.0
    level = float(params.get("level", 50.0)) / 100.0

    x = audio.astype(np.float64).mean(axis=1)

    # Tighten before the gain stages.
    x = lfilter(*butter(2, 95.0 / (fs * 0.5), btype="high"), x)
    x = x * (1.0 + gain * 45.0)

    # Stage 1: asymmetric soft clip (adds even harmonics).
    bias = 0.18
    x = np.tanh(x + bias) - np.tanh(bias)
    # Interstage low-pass to tame fizz.
    x = lfilter(*butter(1, 7000.0 / (fs * 0.5), btype="low"), x)
    # Stage 2 + 3.
    x = np.tanh(x * (1.0 + gain * 6.0))
    x = np.tanh(x * 1.6)

    # Tone stack.
    x = lfilter(*_shelf(fs, 120.0, (bass - 0.5) * 18.0, high=False), x)
    x = lfilter(*_peaking(fs, 700.0, 0.9, (mid - 0.5) * 18.0), x)
    x = lfilter(*_shelf(fs, 3000.0, (treble - 0.5) * 16.0, high=True), x)
    x = lfilter(*_peaking(fs, 4000.0, 1.1, (presence - 0.5) * 14.0), x)

    # Cab.
    x = fftconvolve(x, _cab_ir(fs))[: len(x)]

    # Output level + final brickwall-ish safety clip.
    x = np.tanh(x * (0.4 + level * 1.4))

    out = np.empty((len(x), 2))
    out[:, 0] = x
    out[:, 1] = x
    return out
