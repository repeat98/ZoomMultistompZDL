"""Desktop reference renderer for Klang — ring modulator + frequency shifter.

  Ring mod:    wet = in * cos(carrier)                       -> sum/diff sidebands
  Shift Up:    wet = in*cos(carrier) - hilbert(in)*sin(carrier)   (single sideband, +Hz)
  Shift Down:  wet = in*cos(carrier) + hilbert(in)*sin(carrier)   (single sideband, -Hz)

Frequency shifting uses the analytic signal (scipy.signal.hilbert) so all
partials move by a fixed Hz amount (inharmonic), unlike pitch shifting. The
carrier can be swept by an LFO, and the L/R carriers are detuned for stereo
width.

Knobs (manifest order, 0..100):
  Freq   carrier/shift frequency, ~0.5..2000 Hz (log)
  Mode   0-33 Ring, 34-66 Shift Up, 67-100 Shift Down
  Sweep  LFO motion on the carrier frequency
  Spread stereo carrier detune
  Mix    dry/wet
"""

from __future__ import annotations

import numpy as np
from scipy.signal import hilbert

TWO_PI = 6.28318530717959


def _carrier_phase(n, sr, f_base, sweep):
    t = np.arange(n) / sr
    if sweep > 0.0:
        rate = 0.1 + sweep * 5.9            # 0.1..6 Hz LFO
        depth = sweep * 0.6                 # up to +/-60% carrier swing
        f = f_base * (1.0 + depth * np.sin(TWO_PI * rate * t))
    else:
        f = np.full(n, f_base)
    return TWO_PI * np.cumsum(f) / sr


def _process(mono, analytic_imag, sr, f_base, mode, sweep):
    phase = _carrier_phase(mono.shape[0], sr, f_base, sweep)
    c = np.cos(phase)
    s = np.sin(phase)
    if mode == 0:                            # ring
        return mono * c
    if mode == 1:                            # shift up
        return mono * c - analytic_imag * s
    return mono * c + analytic_imag * s      # shift down


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    freq = float(params.get("freq", 40.0)) / 100.0
    mode_k = float(params.get("mode", 0.0))
    sweep = float(params.get("sweep", 0.0)) / 100.0
    spread = float(params.get("spread", 30.0)) / 100.0
    mix = float(params.get("mix", 60.0)) / 100.0

    f_base = 0.5 * (2.0 ** (freq * 12.0))    # ~0.5 .. ~2000 Hz
    mode = 0 if mode_k <= 33 else (1 if mode_k <= 66 else 2)

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    aimag = np.imag(hilbert(mono))           # 90-degree phase-shifted copy

    # Stereo: detune the carrier slightly between channels.
    fL = f_base * (1.0 - spread * 0.03)
    fR = f_base * (1.0 + spread * 0.03)
    wetL = _process(mono, aimag, sr, fL, mode, sweep)
    wetR = _process(mono, aimag, sr, fR, mode, sweep)

    out = np.empty((x.shape[0], 2))
    out[:, 0] = x[:, 0] * (1.0 - mix) + wetL * mix
    out[:, 1] = x[:, min(1, x.shape[1] - 1)] * (1.0 - mix) + wetR * mix
    return out
