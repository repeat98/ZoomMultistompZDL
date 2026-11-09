"""Generate a simple synthesized drum loop WAV for testing glitch effects.

Usage: python3 tools/audio_preview/make_drum_loop.py out.wav [bars] [bpm]
"""

import sys

import numpy as np
import soundfile as sf

SR = 44100


def _env(n, decay):
    t = np.arange(n) / SR
    return np.exp(-t / decay)


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 50 + 90 * np.exp(-t / 0.03)        # pitch sweep 140 -> 50 Hz
    phase = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(phase) * _env(n, 0.18)
    click = np.random.randn(int(0.004 * SR)) * 0.6
    out = body
    out[: len(click)] += click
    return out * 0.9


def snare():
    n = int(0.2 * SR)
    noise = np.random.randn(n) * _env(n, 0.08)
    tone = np.sin(2 * np.pi * 185 * np.arange(n) / SR) * _env(n, 0.06)
    return (noise * 0.7 + tone * 0.5) * 0.7


def hat(open_=False):
    n = int((0.12 if open_ else 0.035) * SR)
    noise = np.random.randn(n)
    # crude highpass: difference
    noise = np.diff(noise, prepend=0.0)
    return noise * _env(n, 0.05 if open_ else 0.015) * 0.35


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "drums.wav"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    bpm = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

    step = 60.0 / bpm / 4.0                  # 16th note
    steps = bars * 16
    total = int(steps * step * SR) + SR // 2
    buf = np.zeros(total)

    def place(sample, step_idx):
        start = int(step_idx * step * SR)
        end = min(start + len(sample), total)
        buf[start:end] += sample[: end - start]

    for bar in range(bars):
        base = bar * 16
        for s in (0, 4, 8, 12):              # 4-on-the-floor kick
            place(kick(), base + s)
        for s in (4, 12):                    # snare on 2 and 4
            place(snare(), base + s)
        for s in range(0, 16, 2):            # 8th-note hats
            place(hat(open_=(s == 14)), base + s)

    buf *= 0.8 / np.max(np.abs(buf))
    sf.write(out_path, np.column_stack([buf, buf]), SR, subtype="PCM_24")
    print(f"wrote {total / SR:.2f} s drum loop ({bars} bars @ {bpm:g} BPM) -> {out_path}")


if __name__ == "__main__":
    main()
