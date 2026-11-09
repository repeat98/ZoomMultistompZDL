"""Desktop reference renderer for Microloom — a Microcosm-style granular
pitch-shimmer cloud delay.

This is an original effect (not an Airwindows port) that captures the
*signature* sound of granular shimmer pedals like the Hologram Microcosm:

  input -> circular record buffer
        -> granular pitch shifter (delay-line, 2 overlapping grains/voice)
        -> regeneration feedback (grains re-enter the buffer; with Pitch up
           this stacks octaves into a rising shimmer cascade)
        -> reverb wash (Schroeder comb+allpass)
        -> dry/wet mix

It is NOT a full Microcosm clone (no looper, no algorithm modes, no LCD).
It's the achievable core texture, and it's deliberately written so the same
DSP shape can later be ported to the pedal's ctx[3] arena.

Knobs (manifest order, all 0..100):
  Size  grain length, ~23ms..370ms
  Pitch semitones -12..+12 (50 = unison, 100 = +1 octave)
  Dense grain overlap / voice thickness
  Spray random scatter of grain read positions
  Regen feedback regeneration (the cloud build-up)
  Verb  reverb wash amount
  Mix   dry/wet
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

MAX_DELAY = None  # set per render from buffer length


def _comb(x, delay, g):
    # feedback comb: y[n] = x[n] + g*y[n-delay]
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -g
    return lfilter([1.0], a, x)


def _allpass(x, delay, g):
    # Schroeder allpass: y[n] = -g*x[n] + x[n-delay] + g*y[n-delay]
    b = np.zeros(delay + 1)
    b[0] = -g
    b[delay] = 1.0
    a = np.zeros(delay + 1)
    a[0] = 1.0
    a[delay] = -g
    return lfilter(b, a, x)


def _reverb(mono, sr):
    # Freeverb-ish: parallel combs summed, then series allpasses. Tuned at 44.1k.
    comb_delays = [1557, 1617, 1491, 1422, 1277, 1356]
    out = np.zeros_like(mono)
    for d in comb_delays:
        out += _comb(mono, int(d * sr / 44100), 0.84)
    out /= len(comb_delays)
    for d in (225, 556, 441):
        out = _allpass(out, int(d * sr / 44100), 0.5)
    return out


def _shimmer(mono, sr, grain_len, ratio, voices, base_delay, spray, regen):
    """Pitch-shifted feedback delay with in-loop allpass diffusion.

    The feedback loop gain IS `regen`, so sustain is real and multi-second.
    Each pass is read back through a 2-tap granular pitch shifter, so with
    Pitch up every repeat stacks an octave higher -> a rising shimmer cloud.
    Allpass diffusers in the feedback path smear discrete repeats into a wash.
    """
    n = mono.shape[0]
    buf_len = base_delay + grain_len * 2 + int(0.1 * sr) + 8
    buf = np.zeros(buf_len)
    out = np.zeros(n)
    write = 0
    half = max(grain_len // 2, 1)
    inv_half = 1.0 / half

    # Per-voice grain phase, staggered so overlaps fill the window.
    phase = [(grain_len * v // max(voices, 1)) % grain_len for v in range(voices)]

    # Allpass diffusers in the feedback path (unity gain -> don't affect decay).
    ap_lens = [113, 337, 671]
    ap_g = 0.6
    ap_buf = [np.zeros(L) for L in ap_lens]
    ap_idx = [0, 0, 0]

    # Slow random walk per voice -> "spray" scatter of read positions.
    rng = np.random.default_rng(7)
    sway = np.zeros(voices)
    target = rng.standard_normal(voices) * spray
    cnt = 0

    # SHIMMER: how much pitched signal is *added* on top of the clean
    # sustaining feedback. The clean tap carries the tail at the full Regen
    # loop gain (rings for seconds); the pitched tap is an additive octave
    # injection that accumulates into a rising cloud. Kept modest so the loop
    # stays stable.
    SHIMMER = 0.45
    lp = 0.0  # one-pole state for a gentle feedback low-cut (stops mud build-up)

    feed = 0.0
    for i in range(n):
        buf[write] = mono[i] + feed

        if cnt <= 0:
            target = rng.standard_normal(voices) * spray
            cnt = int(0.04 * sr)
        sway += (target - sway) * 0.001
        cnt -= 1

        # Coherent clean tap -> sustaining tail at the full Regen gain.
        clean = _read(buf, write - base_delay, buf_len)

        # Pitched granular taps -> rising shimmer injected on top.
        acc = 0.0
        for v in range(voices):
            p = phase[v]
            d1 = p
            d2 = (p + half) % grain_len
            e1 = (half - abs(half - d1)) * inv_half
            e2 = (half - abs(half - d2)) * inv_half
            off = base_delay + sway[v]
            acc += _read(buf, write - off - d1, buf_len) * e1
            acc += _read(buf, write - off - d2, buf_len) * e2
            p += (1.0 - ratio)
            if p >= grain_len:
                p -= grain_len
            elif p < 0:
                p += grain_len
            phase[v] = p
        acc /= max(voices, 1)

        mixed = regen * clean + SHIMMER * acc

        # Diffuse through the allpass chain.
        x = mixed
        for k in range(len(ap_lens)):
            bk = ap_buf[k]
            ik = ap_idx[k]
            d = bk[ik]
            y = -ap_g * x + d
            bk[ik] = x + ap_g * y
            ap_idx[k] = (ik + 1) % ap_lens[k]
            x = y

        # Gentle low-cut on the feedback path to keep the cloud from muddying.
        lp += 0.0008 * (x - lp)
        feed = x - lp

        out[i] = feed
        write += 1
        if write >= buf_len:
            write = 0
    return out


def _read(buf, pos, buf_len):
    # Fractional read with wrap + linear interpolation.
    pos = pos % buf_len
    i0 = int(np.floor(pos))
    frac = pos - i0
    i1 = i0 + 1
    if i1 >= buf_len:
        i1 = 0
    return buf[i0] * (1.0 - frac) + buf[i1] * frac


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    size = float(params.get("size", 55.0)) / 100.0
    pitch = float(params.get("pitch", 100.0))
    dense = float(params.get("dense", 60.0)) / 100.0
    spray = float(params.get("spray", 40.0)) / 100.0
    regen = float(np.clip(float(params.get("regen", 55.0)) / 100.0 * 0.9, 0.0, 0.9))
    verb = float(params.get("verb", 60.0)) / 100.0
    mix = float(params.get("mix", 50.0)) / 100.0

    grain_len = int(2048 + size * (12288 - 2048))    # ~46ms..325ms @44.1k
    base_delay = grain_len + int(0.04 * sr)          # feedback-loop delay
    semitones = (pitch - 50.0) / 50.0 * 12.0
    ratio = 2.0 ** (semitones / 12.0)
    voices = int(round(2 + dense * 2))               # 2..4 overlapping grains
    spray_samps = spray * 0.05 * sr                  # up to ~50ms scatter

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    # Add a tail of silence so the cloud can ring out.
    tail_samps = int(tail * sr)
    mono = np.concatenate([mono, np.zeros(tail_samps)])

    wet = _shimmer(mono, sr, grain_len, ratio, voices, base_delay, spray_samps, regen)
    if verb > 0.0:
        wet = (1.0 - verb) * wet + verb * _reverb(wet, sr)

    # Light makeup + soft safety clip on the wet cloud.
    wet = np.tanh(wet * 1.2)

    dry = np.concatenate([x, np.zeros((tail_samps, x.shape[1]))], axis=0)
    # Stereo-widen the wet with a tiny inter-channel delay.
    sd = int(0.011 * sr)
    wetL = wet
    wetR = np.concatenate([np.zeros(sd), wet[:-sd]]) if sd < len(wet) else wet
    out = np.empty((len(wet), 2))
    out[:, 0] = dry[:, 0] * (1.0 - mix) + wetL * mix
    out[:, 1] = dry[:, min(1, dry.shape[1] - 1)] * (1.0 - mix) + wetR * mix
    return out
