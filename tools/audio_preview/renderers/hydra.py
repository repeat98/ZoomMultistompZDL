"""Desktop reference renderer for Hydra — two extra playback heads on one ring.

The dry signal is written to a delay ring. Two more heads read the SAME ring at
different rates, re-triggered every `Window` samples from a point one window
behind the write head:

  * the 2x head closes the gap at 1 sample per sample, so in one window it
    consumes TWO windows of history and lands flush on the write head — a
    double-time ghost, an octave up.
  * the 0.5x head falls behind instead, covering half a window per window and
    lagging at most 1.5 windows — a dragging, octave-down smear.

The Window knob is what makes this one effect instead of two. Short windows
(a few ms) make the re-trigger rate audible as pitch, which IS granular pitch
shifting: an octave-up and an octave-down layer sitting in time with the dry.
Long windows (100 ms .. 1 s) put the re-trigger down at rhythmic rates, so the
layers become double-time hits and a half-time drag against the beat.

Re-trigger is a hard cut with a short raised-cosine fade, not an overlapping
crossfade: on drums the transient is the point, and the grit at short windows
suits this pack. Microloom is the smooth shimmer if you want that instead.

Knobs (manifest order, 0..100):
  Window  re-trigger length, ~3 ms .. 1 s (exponential)
  Fast    level of the 2x (octave-up / double-time) head
  Slow    level of the 0.5x (octave-down / half-time) head
  Tone    low-pass on the two layers only (the 2x head gets spiky on cymbals)
  Mix     dry/wet
"""

from __future__ import annotations

import numpy as np

WIN_MIN_MS = 3.0
WIN_MAX_MS = 1000.0


def _read(buf, pos, mask):
    """Linear-interpolated read from a power-of-two ring."""
    i0 = int(pos) & mask
    i1 = (i0 + 1) & mask
    frac = pos - np.floor(pos)
    return buf[i0] * (1.0 - frac) + buf[i1] * frac


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    win_n    = float(params.get("window", 50.0)) / 100.0
    fast_lvl = float(params.get("fast", 60.0)) / 100.0
    slow_lvl = float(params.get("slow", 60.0)) / 100.0
    tone     = float(params.get("tone", 50.0)) / 100.0
    mix      = float(params.get("mix", 50.0)) / 100.0

    # exponential window: 3 ms .. 1 s
    win_ms = WIN_MIN_MS * ((WIN_MAX_MS / WIN_MIN_MS) ** win_n)
    W = max(int(sr * win_ms * 0.001), 32)

    x = audio.astype(np.float64)
    if x.ndim == 1:
        x = x[:, None]
    tail_samps = int(tail * sr) if tail else 0
    mono = np.concatenate([x.mean(axis=1), np.zeros(tail_samps)])
    n = mono.shape[0]

    # ring must hold the slow head's worst-case 1.5-window lag, with headroom
    size = 1
    while size < W * 3:
        size <<= 1
    buf = np.zeros(size)
    mask = size - 1

    fade = min(max(W // 8, 8), 128)
    inv_fade = 1.0 / fade
    lp_coef = 0.02 + tone * 0.55            # one-pole LP on the layers

    wet = np.zeros(n)
    wp = 0
    fast_pos = 0.0
    slow_pos = 0.0
    grain_t = W                             # force a re-trigger on sample 0
    lp = 0.0

    for i in range(n):
        buf[wp & mask] = mono[i]

        if grain_t >= W:                    # re-trigger both heads one window back
            grain_t = 0
            fast_pos = float(wp - W)
            slow_pos = float(wp - W)

        # short raised-cosine fade at each seam so the hard cut doesn't click
        if grain_t < fade:
            env = 0.5 - 0.5 * np.cos(np.pi * grain_t * inv_fade)
        elif grain_t > W - fade:
            env = 0.5 - 0.5 * np.cos(np.pi * (W - grain_t) * inv_fade)
        else:
            env = 1.0

        f = _read(buf, fast_pos, mask)
        s = _read(buf, slow_pos, mask)
        fast_pos += 2.0
        slow_pos += 0.5
        grain_t += 1
        wp += 1

        layers = (f * fast_lvl + s * slow_lvl) * env
        lp += lp_coef * (layers - lp)        # Tone applies to the layers only
        wet[i] = lp

    dry = np.concatenate([x, np.zeros((tail_samps, x.shape[1]))], axis=0)
    out = np.empty((n, 2))
    for ch in range(2):
        d = dry[:, min(ch, dry.shape[1] - 1)]
        y = d + wet
        y = np.clip(y, -1.0, 1.0)
        y = 1.5 * y - 0.5 * y ** 3           # soft-clip the stacked layers
        out[:, ch] = d * (1.0 - mix) + y * mix
    return out
