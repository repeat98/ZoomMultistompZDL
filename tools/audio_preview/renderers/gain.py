"""Desktop reference renderer for the GAIN pedal DSP.

Mirrors gain.c: out += fx * level. On the pedal the raw knob lands ~0.14 at
full and is multiplied by 8; on desktop the knob arrives as its plain 0..100
value, so we map it musically: knob 50 (default) -> unity, knob 100 -> 2x.
The `Mix` knob exists only because firmware needs >=2 knobs; gain.c ignores it,
so we do too.
"""

from __future__ import annotations

import numpy as np


def render(audio, sample_rate, params, tail, root):
    level = float(params.get("level", 50.0))
    gain = level / 50.0  # default 50 -> unity, 100 -> 2x
    return audio.astype(np.float64) * gain
