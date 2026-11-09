"""Desktop reference renderer for the TapeHack pedal DSP.

Mirrors tapehack.c (an Airwindows TapeHack port). Stateless saturation:

    dry  = x * inputGain
    s    = clip(dry * boost, +/-2.305929)
    wet  = sin(s)                      # odd Taylor sin on the pedal; real sin here
    out  = (dry * (1 - drive) + wet * drive) * outputGain

`Drive` is both a preamp boost (1..3x) and the wet/dry blend, matching the
source. Knob mapping uses the manifest ranges directly (the pedal's 0.14/x8
scaling is a firmware artifact, not part of the musical intent):

  - Input  0..100  -> 0..2x preamp trim          (default 50 -> 1x)
  - Drive  0..100  -> blend/boost 0..1            (default 0  -> clean)
  - Output 0..150  -> output trim, default 100 -> unity
"""

from __future__ import annotations

import numpy as np

CLIP_LIMIT = 2.305929


def render(audio, sample_rate, params, tail, root):
    input_gain = float(params.get("input", 50.0)) / 100.0 * 2.0
    drive = float(np.clip(float(params.get("drive", 0.0)) / 100.0, 0.0, 1.0))
    output_gain = float(params.get("output", 100.0)) / 100.0
    boost = 1.0 + drive * 2.0

    x = audio.astype(np.float64)
    dry = x * input_gain
    s = np.clip(dry * boost, -CLIP_LIMIT, CLIP_LIMIT)
    wet = np.sin(s)
    return (dry * (1.0 - drive) + wet * drive) * output_gain
