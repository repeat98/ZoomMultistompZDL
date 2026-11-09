"""Desktop reference renderer for the PurestDrive pedal DSP.

Mirrors purestdrive.c (an Airwindows PurestDrive port):

    sat   = sin(dry)
    blend = |prev + sat| * 0.5 * intensity        (clamped to 1)
    wet   = dry * (1 - blend) + sat * blend
    prev  = sin(dry)

The adaptive `blend` lets transients/highs through more openly than a static
dry/wet, which is the "Purest" character. Differences vs the pedal build:

  - Real sin() instead of the pedal's Bhaskara approximation (desktop has it).
  - previousSample runs continuously across the stream. The pedal resets it
    every 8-sample block (a documented hardware-state limitation), so this is
    actually closer to the original Airwindows algorithm.
  - `Drive` maps 0..100 -> intensity 0..1 (the pedal's 0.14/x8 fudge is a
    firmware scaling artifact we don't reproduce).
  - `Mix` (unused by purestdrive.c) is honored here as a final dry/wet blend,
    since the knob exists and the behavior is the obvious intent.
"""

from __future__ import annotations

import numpy as np


def render(audio, sample_rate, params, tail, root):
    intensity = float(np.clip(float(params.get("drive", 50.0)) / 100.0, 0.0, 1.0))
    wet_mix = float(np.clip(float(params.get("mix", 100.0)) / 100.0, 0.0, 1.0))

    x = audio.astype(np.float64)
    out = np.empty_like(x)
    for ch in range(x.shape[1]):
        col = x[:, ch]
        dst = out[:, ch]
        prev = 0.0
        for n in range(col.shape[0]):
            dry = col[n]
            sat = np.sin(dry)
            blend = abs(prev + sat) * 0.5 * intensity
            if blend > 1.0:
                blend = 1.0
            wet = dry * (1.0 - blend) + sat * blend
            dst[n] = dry * (1.0 - wet_mix) + wet * wet_mix
            prev = sat
    return out
