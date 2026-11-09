"""Desktop reference renderer for Corrupt — an EarthQuaker Devices Data
Corrupter style monophonic harmonizing PLL synth-fuzz.

Signal flow:
  1. Track the input fundamental (autocorrelation per frame). Octave-ambiguous
     frames produce the glitchy octave jumps the pedal is loved for.
  2. Synthesize a square-wave MASTER oscillator locked to that pitch (octave
     selectable: unison / -1 / -2, the Master Oscillator toggle).
  3. Derive a SUBHARMONIC square one octave below the master (the analog pedal
     uses flip-flop frequency division; perfect octaves).
  4. Add a HARMONY square at a selectable interval, frequency-modulated
     (vibrato) by Rate/Depth -> the warbly sci-fi wobble.
  5. An envelope follower makes the synth voices track your picking dynamics
     and gate out when you stop.

Square waves are not band-limited on purpose: the aliasing is part of the
digital, gnarly Data Corrupter character (tamed slightly by a final low-pass).

Knobs (manifest order, 0..100):
  Master octave of the master oscillator (0 unison, 50 -1oct, 100 -2oct)
  Sub    subharmonic voice level
  Harm   harmony interval (unison/5th/oct/4th/-oct/+12th)
  Rate   FM vibrato rate on the harmony voice
  Depth  FM vibrato depth (semitones)
  Mix    dry/synth blend
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt

TWO_PI = 6.28318530717959
HARM_INTERVALS = [0.0, 7.0, 12.0, 5.0, -12.0, 19.0]  # semitones to choose from


def _track_f0(mono, sr, fmin=70.0, fmax=700.0, frame=2048, hop=512):
    n = mono.shape[0]
    minlag = int(sr / fmax)
    maxlag = int(sr / fmin)
    nfft = 1
    while nfft < 2 * frame:
        nfft <<= 1

    # Track on a low-passed copy so detection locks to the fundamental, not
    # bright pick/transient energy. (A real guitar tracks easier than this.)
    b, a = butter(2, 900.0 / (sr * 0.5), btype="low")
    mono = filtfilt(b, a, mono)

    centers = []
    f0s = []
    k = 0
    while k * hop + frame <= n:
        seg = mono[k * hop:k * hop + frame].astype(np.float64)
        seg = seg - seg.mean()
        rms = np.sqrt(np.mean(seg * seg))
        if rms < 1.5e-3:
            f0 = 0.0
        else:
            sp = np.fft.rfft(seg * np.hanning(frame), nfft)
            ac = np.fft.irfft(sp * np.conj(sp))[:maxlag + 2]
            if len(ac) <= minlag + 1:
                f0 = 0.0
            else:
                window = ac[minlag:maxlag + 1]
                peakval = window.max()
                # Octave-error fix: take the SHORTEST-period (highest-freq)
                # strong local peak, not the global max (which is often a
                # subharmonic multiple of the true period).
                lag = minlag + int(np.argmax(window))
                thr = 0.82 * peakval
                for L in range(minlag + 1, maxlag):
                    if ac[L] >= thr and ac[L] >= ac[L - 1] and ac[L] >= ac[L + 1]:
                        lag = L
                        break
                conf = peakval / (ac[0] + 1e-12)
                f0 = sr / lag if conf > 0.35 else 0.0
        centers.append(k * hop + frame // 2)
        f0s.append(f0)
        k += 1

    # Per-sample f0: hold across the frame grid (snappy, PLL-like re-lock).
    out = np.zeros(n)
    if centers:
        idx = np.searchsorted(centers, np.arange(n)).clip(0, len(centers) - 1)
        out = np.array(f0s)[idx]
    return out


def _env_follow(mono, sr, atk_ms=4.0, rel_ms=90.0):
    a_a = np.exp(-1.0 / (atk_ms * 0.001 * sr))
    a_r = np.exp(-1.0 / (rel_ms * 0.001 * sr))
    env = np.zeros_like(mono)
    e = 0.0
    for i in range(mono.shape[0]):
        v = abs(mono[i])
        e = (a_a if v > e else a_r) * e + (1.0 - (a_a if v > e else a_r)) * v
        env[i] = e
    return env


def _sq(phase):
    return 1.0 if (phase - np.floor(phase)) < 0.5 else -1.0


def render(audio, sample_rate, params, tail, root):
    sr = sample_rate
    master = float(params.get("master", 0.0)) / 100.0
    sub_lvl = float(params.get("sub", 60.0)) / 100.0
    harm = float(params.get("harm", 50.0)) / 100.0
    rate = float(params.get("rate", 40.0)) / 100.0
    depth = float(params.get("depth", 35.0)) / 100.0
    mix = float(params.get("mix", 85.0)) / 100.0

    oct_sel = int(round(master * 2))                  # 0,1,2 -> /1,/2,/4
    master_ratio = 2.0 ** (-oct_sel)
    sub_ratio = master_ratio * 0.5                    # one octave below master
    h_idx = min(int(harm * len(HARM_INTERVALS)), len(HARM_INTERVALS) - 1)
    harm_ratio = master_ratio * (2.0 ** (HARM_INTERVALS[h_idx] / 12.0))
    fm_rate = 0.5 + rate * 11.5                       # Hz
    fm_depth = depth * 3.0                            # semitones

    x = audio.astype(np.float64)
    mono = x.mean(axis=1)
    f0 = _track_f0(mono, sr)
    env = _env_follow(mono, sr)

    # Smooth f0 a touch to avoid clicks but keep snappy re-locks.
    sm = np.exp(-1.0 / (0.005 * sr))
    f = 0.0
    for i in range(f0.shape[0]):
        f = sm * f + (1.0 - sm) * f0[i] if f0[i] > 0 else f0[i]
        f0[i] = f

    n = mono.shape[0]
    wet = np.zeros(n)
    pm = ps = ph = 0.0
    for i in range(n):
        fi = f0[i]
        if fi > 0.0:
            pm += fi * master_ratio / sr
            ps += fi * sub_ratio / sr
            fm = 2.0 ** (fm_depth * np.sin(TWO_PI * fm_rate * i / sr) / 12.0)
            ph += fi * harm_ratio * fm / sr
        e = env[i]
        wet[i] = e * (_sq(pm) + sub_lvl * _sq(ps) + 0.55 * _sq(ph))

    # Tame the worst aliasing and normalize the squared-up sum.
    a = np.exp(-TWO_PI * 6000.0 / sr)
    lp = 0.0
    for i in range(n):
        lp = (1.0 - a) * wet[i] + a * lp
        wet[i] = lp
    peak = np.max(np.abs(wet))
    if peak > 1e-6:
        wet *= 0.7 / peak

    out = np.empty((n, 2))
    out[:, 0] = x[:, 0] * (1.0 - mix) + wet * mix
    out[:, 1] = x[:, min(1, x.shape[1] - 1)] * (1.0 - mix) + wet * mix
    return out
