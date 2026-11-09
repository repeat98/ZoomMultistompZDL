"""Desktop reference renderer for Spiral — a delay whose repeats climb (or sink).

A pitch shift lives INSIDE the feedback loop, so it compounds: repeat 1 is one
step away, repeat 2 is two steps, repeat 3 is three, an endless staircase that
fades out as feedback decays. Shepard-tone territory, but with a small interval
you hear it creep rather than jump.

The tap is grain-re-triggered and read at `ratio`, so one reader both delays and
pitch-shifts (the same trick as Hydra's heads). Two controls sit on that ratio
and cover the two ways to read "the delay rises in pitch":

  Rise   a constant ratio != 1. Discrete: each repeat is one step from the last.
         Bipolar, unity at centre — left of centre the repeats sink instead.
  Glide  depth of an onset-triggered ramp ON that ratio, and Span is how long it
         takes. A note resets the ramp to ZERO and it then climbs toward Glide's
         depth over Span, so the repeats begin at pitch and drift away over a
         while -- a riser. Deliberately not a swoop that settles back.

Set Glide to 0 for a pure staircase; set Rise to centre and Glide up for a pure
glide with no net transposition; use both for a climb that also swoops.

The ratio mapping is piecewise LINEAR, not 2^(semitones/12): the pedal port
cannot call exp2 without pulling in a helper, and equal temperament is not the
point here.

Knobs (manifest order, 0..100):
  Time    delay time, ~40 ms .. 1.2 s
  Feedbk  repeats
  Rise    pitch step per repeat: 0 = octave down, 50 = unity, 100 = octave up
  Glide   how far the pitch travels over the rise (depth)
  Span    how long that rise takes, ~0.2 s .. 8 s
  Tone    low-pass inside the loop, so the climb dulls instead of turning harsh
  Mix     dry/wet
"""

from __future__ import annotations

import numpy as np

GRAIN_MS = 55.0          # tap grain length; short enough to track, long enough to be smooth


def _read(buf, pos, mask):
    i0 = int(pos) & mask
    i1 = (i0 + 1) & mask
    frac = pos - np.floor(pos)
    return buf[i0] * (1.0 - frac) + buf[i1] * frac


def _ratio_from_rise(rise: float) -> float:
    """Piecewise linear, unity at centre: 0 -> 0.5 (oct down), 1 -> 2.0 (oct up)."""
    if rise < 0.5:
        return 0.5 + rise                      # 0.5 .. 1.0
    return 1.0 + (rise - 0.5) * 2.0            # 1.0 .. 2.0


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    time_n = float(params.get("time", 45.0)) / 100.0
    fb_n   = float(params.get("feedbk", 60.0)) / 100.0
    rise_n = float(params.get("rise", 62.0)) / 100.0
    glide_n= float(params.get("glide", 45.0)) / 100.0
    span_n = float(params.get("span", 45.0)) / 100.0
    tone_n = float(params.get("tone", 50.0)) / 100.0
    mix    = float(params.get("mix", 50.0)) / 100.0

    delay_s = 0.04 + time_n * time_n * 1.16        # ~40 ms .. 1.2 s, squared for feel
    D = max(int(delay_s * sr), 64)
    fb = fb_n * 0.965                              # long tails, still short of runaway
    base_ratio = _ratio_from_rise(rise_n)
    # Glide pushes the ratio further in whichever direction Rise points.
    glide_dir = 1.0 if rise_n >= 0.5 else -1.0
    glide_amt = glide_n * 0.6
    lp_coef = 0.03 + tone_n * 0.5

    G = max(int(GRAIN_MS * 0.001 * sr), 64)        # grain length
    inv_G = 1.0 / G

    x = audio.astype(np.float64)
    if x.ndim == 1:
        x = x[:, None]
    tail_samps = int(tail * sr) if tail else int(3.0 * sr)
    mono = np.concatenate([x.mean(axis=1), np.zeros(tail_samps)])
    n = mono.shape[0]

    size = 1
    while size < (D + G) * 3:
        size <<= 1
    buf = np.zeros(size)
    mask = size - 1

    wet = np.zeros(n)
    wp = 0
    tap = 0.0
    grain_t = G
    lp = 0.0
    env_f = env_s = 0.0
    ramp = 0.0
    # Span: how long the rise takes. A note resets the ramp to 0 and it climbs
    # toward 1, so the repeats START at pitch and drift away over Span -- the
    # "slowly rises for a while" behaviour, not a swoop settling back.
    span_s = 0.2 + span_n * span_n * 7.8           # ~0.2 s .. 8 s
    ramp_k = 1.0 - np.exp(-1.0 / (span_s * sr))
    a_f, a_s = 0.02, 0.0008
    cool = 0

    for i in range(n):
        dry = mono[i]
        ax = abs(dry)
        env_f += a_f * (ax - env_f)
        env_s += a_s * (ax - env_s)
        # onset: fast envelope jumps clear of the slow one
        if cool <= 0 and env_f > env_s * 1.7 + 0.008:
            ramp = 0.0                             # a note restarts the climb from pitch
            cool = int(0.05 * sr)
        cool -= 1
        ramp += ramp_k * (1.0 - ramp)              # ... and it rises from there

        ratio = base_ratio * (1.0 + glide_amt * ramp * glide_dir)
        if ratio < 0.25:
            ratio = 0.25
        elif ratio > 4.0:
            ratio = 4.0

        if grain_t >= G:                           # re-trigger the tap D behind
            grain_t = 0
            tap = float(wp - D)

        if grain_t < G * 0.5:
            env = grain_t * inv_G * 2.0
        else:
            env = (G - grain_t) * inv_G * 2.0
        env = env * env * (3.0 - 2.0 * env) if env < 1.0 else 1.0

        echo = _read(buf, tap, mask) * env
        tap += ratio
        grain_t += 1

        lp += lp_coef * (echo - lp)                # Tone inside the loop
        e = lp
        # soft-clip the feedback so a compounding shift cannot run away
        f = dry + e * fb
        f = np.clip(f, -1.0, 1.0)
        buf[wp & mask] = 1.5 * f - 0.5 * f ** 3
        wp += 1

        wet[i] = e

    dry_pad = np.concatenate([x, np.zeros((tail_samps, x.shape[1]))], axis=0)
    out = np.empty((n, 2))
    for ch in range(2):
        d = dry_pad[:, min(ch, dry_pad.shape[1] - 1)]
        out[:, ch] = d * (1.0 - mix) + np.clip(d + wet, -1.0, 1.0) * mix
    return out
