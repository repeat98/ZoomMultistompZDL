"""Generate a dry guitar-like test signal (Karplus-Strong plucks) as a WAV.

Usage: python3 tools/audio_preview/make_test_signal.py out.wav
"""

import sys

import numpy as np
import soundfile as sf

SR = 44100


def pluck(freq, dur, sr=SR, decay=0.996):
    n = int(sr / freq)
    rng = np.random.default_rng(int(freq))
    buf = rng.standard_normal(n)
    total = int(dur * sr)
    out = np.empty(total)
    idx = 0
    for i in range(total):
        out[i] = buf[idx]
        nxt = (idx + 1) % n
        buf[idx] = 0.5 * (buf[idx] + buf[nxt]) * decay
        idx = nxt
    # short fade out so notes don't click
    fade = int(0.02 * sr)
    out[-fade:] *= np.linspace(1.0, 0.0, fade)
    return out


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "input.wav"

    # Open strings of a guitar, a simple ascending arpeggio.
    notes = [82.41, 110.0, 146.83, 196.0, 246.94, 329.63]  # E2 A2 D3 G3 B3 E4
    note_dur = 0.7
    samples = np.concatenate([pluck(f, note_dur) for f in notes])
    # let the last note ring a little
    samples = np.concatenate([samples, np.zeros(int(0.6 * SR))])
    samples *= 0.85 / np.max(np.abs(samples))  # hot, like the pedal's effect-loop signal

    # Mono source -> stereo (identical channels; stereo effects add the width).
    stereo = np.column_stack([samples, samples])
    sf.write(out_path, stereo, SR, subtype="PCM_24")
    print(f"wrote {len(samples) / SR:.2f} s -> {out_path}")


if __name__ == "__main__":
    main()
