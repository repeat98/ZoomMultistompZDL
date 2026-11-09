#!/usr/bin/env python3
"""Decode a NAMProf recording into numbers, and say what they mean.

NAMProf plays its results as tone bursts (689 Hz = 0, 1378 Hz = 1; 10 ms burst,
5 ms gap; 32 bits per word, MSB first; 0.5 s between frames). Record the
pedal's DIRECT output -- NAMProf alone in the patch, nothing after it -- for at
least 15 seconds once the tones start, save as WAV, and run:

    python3 tools/decode_namprof.py recording.wav

Works at any sample rate: bursts are found in seconds and classified by energy
at the two exact tone frequencies, so it does not care about recording level
or 44.1 vs 48 kHz. A frame is only accepted if its sync word and XOR checksum
both match, so a noisy recording fails loudly instead of reporting nonsense.
"""
import argparse
import sys
import numpy as np
import soundfile as sf

WORDS = ['sync', 'period', 'avg', 'peak', 'min', 'arena_base', 'arena_end',
         'arena_mar', 'l1dcfg', 'l2cfg', 'weights', 'ctx', 'fx', 'check']
SYNC = 0x5A5AA5A5
F0, F1 = 44100 / 64, 44100 / 32          # triangle periods of 64 and 32 samples
EMULATED = 18612                          # emulated cycles/callback, same kernel


def goertzel(x, f, sr):
    w = 2 * np.pi * f / sr
    c = 2 * np.cos(w)
    s1 = s2 = 0.0
    for v in x:
        s0 = v + c * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def bursts(x, sr):
    """(start, end) sample index of every tone burst."""
    win = max(1, int(sr * 0.002))
    env = np.sqrt(np.convolve(x * x, np.ones(win) / win, mode='same'))
    thr = 0.25 * np.percentile(env, 99.5)
    on = env > thr
    edges = np.flatnonzero(np.diff(on.astype(np.int8)))
    if on[0]:
        edges = np.r_[0, edges]
    if on[-1]:
        edges = np.r_[edges, len(on) - 1]
    out = []
    for a, b in zip(edges[0::2], edges[1::2]):
        if (b - a) >= sr * 0.006:                 # real bursts are 10 ms
            out.append((a, b))
    return out


def decode(path):
    x, sr = sf.read(path, dtype='float64')
    if x.ndim > 1:
        x = x.mean(axis=1)
    bs = bursts(x, sr)
    if len(bs) < 32 * len(WORDS):
        sys.exit(f"only {len(bs)} bursts found -- record longer, or check the tones are audible")
    # frame boundaries: gaps far longer than the 5 ms inter-bit gap
    starts = [0] + [i for i in range(1, len(bs)) if (bs[i][0] - bs[i - 1][1]) > sr * 0.2]
    need = 32 * len(WORDS)
    for s in starts:
        seg = bs[s:s + need]
        if len(seg) < need:
            continue
        bits = []
        for a, b in seg:
            core = x[a + (b - a) // 5: b - (b - a) // 5]
            bits.append(1 if goertzel(core, F1, sr) > goertzel(core, F0, sr) else 0)
        words = [int(''.join(map(str, bits[k * 32:(k + 1) * 32])), 2) for k in range(len(WORDS))]
        chk = 0
        for v in words[1:13]:
            chk ^= v
        if words[0] == SYNC and words[13] == chk:
            return dict(zip(WORDS, words))
    sys.exit("no frame passed sync + checksum -- record the direct output with nothing after NAMProf")


def region(addr):
    if 0x11F00000 <= addr < 0x11F08000: return 'L1D SRAM (on-chip, fastest)'
    if 0x11800000 <= addr < 0x11840000: return 'L2 SRAM (on-chip)'
    if 0x80000000 <= addr < 0x80020000: return 'shared RAM (on-chip, uncached)'
    if 0xC0000000 <= addr < 0xC1000000: return 'DDR, first 16 MB (cacheable at boot)'
    if 0xC0000000 <= addr < 0xE0000000: return 'DDR above 16 MB (NOT cacheable at boot)'
    return 'unknown region'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('wav')
    ap.add_argument('--emulated', type=int, default=EMULATED,
                    help='emulated cycles for the measured kernel (18612 = power-of-two TREC; '
                         '22040 = exact-ring TREC, NAMProf2)')
    a = ap.parse_args()
    r = decode(a.wav)
    emulated = a.emulated
    l1d = {0: 0, 1: 4, 2: 8, 3: 16}.get(r['l1dcfg'] & 7, 32)
    l2 = {0: 0, 1: 32, 2: 64, 3: 128, 4: 256}.get(r['l2cfg'] & 7, 256)
    size = r['arena_end'] - r['arena_base']
    print("raw words:")
    for k, v in r.items():
        print(f"  {k:<11} 0x{v:08x}  {v}")
    print()
    if not r['period']:
        print("timer did not run (period 0) -- timing inconclusive; addresses below still valid")
    else:
        # CAUTION: 'period' is counter ticks between callbacks. On the first
        # hardware run (2026-09-25) it was 10,724 -- a 59 MHz clock if taken at
        # face value, implausible for a C674x, and it made the model look 3.5x
        # over budget while 6/8 rate (79% of the work) plays clean. The counter
        # evidently does not run in wall-clock time between callbacks (most
        # likely it pauses while the CPU idles), so 'period' is NOT the budget.
        # Only same-context comparisons (model cycles vs emulated cycles) are
        # safe. See docs/NAM-RUNTIME-INVESTIGATION.md, NAMProf section.
        print(f"period      {r['period']} counter ticks between callbacks "
              f"(NOT the budget -- see note in this script)")
        for k in ('min', 'avg', 'peak'):
            print(f"model {k:<5} {r[k]:>7} cycles")
        print(f"emulated    {emulated:>7} cycles (same code, no memory model)")
        for k in ('min', 'avg'):
            stall = r[k] - emulated
            print(f"=> {k}: {stall} cycles ({100*stall/max(r[k],1):.0f}%) waiting on memory"
                  + (" or interrupts" if k != 'min' else ""))
        print(f"   peak - avg = {r['peak']-r['avg']} cycles of variation (interrupts land here)")
    print()
    print(f"arena       0x{r['arena_base']:08x} .. 0x{r['arena_end']:08x} ({size} bytes) -> {region(r['arena_base'])}")
    print(f"arena MAR   {r['arena_mar'] & 1} ({'cacheable' if r['arena_mar'] & 1 else 'NOT cacheable'})")
    print(f"weights     0x{r['weights']:08x} -> {region(r['weights'])}")
    print(f"ctx         0x{r['ctx']:08x} -> {region(r['ctx'])}")
    print(f"cache       L1D {l1d} KB, L2 {l2} KB")


if __name__ == '__main__':
    main()
