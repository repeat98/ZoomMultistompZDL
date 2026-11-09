"""Desktop reference renderer for Shatter — a stutter / beat-repeat glitch
processor aimed at drum machines and rhythmic material.

The signal is cut into slices on a grid (Rate). For each slice, with
probability Chance, the slice is "glitched":
  - Reverse: play the slice backwards, OR
  - Stutter: capture the first sub-slice and machine-gun retrigger it to fill
    the slice (Repeat sets how many subdivisions).
Then the whole wet path can be bitcrushed + downsampled (Crush) for lo-fi
grit. Left/right share the same glitch decisions so drum hits stay coherent.

Short raised-cosine fades at slice and sub-slice boundaries keep the retriggers
punchy without harsh digital clicks.

Knobs (manifest order, 0..100):
  Rate    slice length, ~400ms (slow) .. ~30ms (chopped)
  Chance  probability a slice is glitched
  Repeat  stutter subdivisions per slice
  Reverse probability a glitched slice is reversed instead of stuttered
  Crush   bitcrush + sample-rate reduction amount
  Mix     dry/wet
"""

from __future__ import annotations

import numpy as np


def _fade(seg, fade):
    if fade <= 0 or seg.shape[0] < 2 * fade:
        return seg
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, fade))
    seg = seg.copy()
    seg[:fade] *= ramp[:, None]
    seg[-fade:] *= ramp[::-1][:, None]
    return seg


def _crush(sig, bits, downsample):
    out = sig
    if downsample > 1:
        held = sig[::downsample]
        out = np.repeat(held, downsample, axis=0)[: sig.shape[0]]
    if bits < 16:
        q = 2.0 ** bits
        out = np.round(out * q) / q
    return out


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    rate = float(params.get("rate", 50.0)) / 100.0
    chance = float(params.get("chance", 55.0)) / 100.0
    repeat = float(params.get("repeat", 45.0)) / 100.0
    reverse_p = float(params.get("reverse", 30.0)) / 100.0
    crush = float(params.get("crush", 35.0)) / 100.0
    mix = float(params.get("mix", 100.0)) / 100.0

    x = audio.astype(np.float64)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    n = x.shape[0]

    slice_len = int((0.4 - rate * 0.37) * sr)        # ~400ms .. ~30ms
    slice_len = max(slice_len, int(0.02 * sr))
    repeats = int(round(2 + repeat * 14))            # 2 .. 16 subdivisions
    bits = 16 - int(round(crush * 12)) if crush > 0.01 else 16   # 16 .. 4
    downsample = 1 + int(round(crush * 10)) if crush > 0.01 else 1
    xf = max(int(0.0015 * sr), 1)                    # ~1.5ms boundary fade

    rng = np.random.default_rng(424242)
    out = x.copy()

    pos = 0
    while pos + slice_len <= n:
        sl = slice_len
        if rng.random() < chance:
            if rng.random() < reverse_p:
                seg = x[pos:pos + sl][::-1].copy()
            else:
                sub_len = max(sl // repeats, int(0.008 * sr))
                sub = _fade(x[pos:pos + sub_len].copy(), min(xf, sub_len // 4))
                reps = int(np.ceil(sl / sub_len))
                seg = np.tile(sub, (reps, 1))[:sl]
            seg = _fade(seg, xf)
            out[pos:pos + sl] = seg
        pos += sl

    if crush > 0.01:
        out = _crush(out, bits, downsample)

    return x * (1.0 - mix) + out * mix
