#!/usr/bin/env python3
"""Is a Zoom effect binary readable, or is it encrypted/signed?

The "+" MultiStomp pedals (MS-50G+, MS-60B+, MS-70CDR+) use ZD2 containers
rather than the ZDL ones this repo builds. Whether custom effects are feasible
there turns on one question that has to be answered BEFORE anyone spends real
time on it: is the payload analysable at all?

  * readable structure, low-to-moderate entropy, recognisable headers
        -> it is plain code. A reverse-engineering job like the ZDL one, and
           docs/STATE-ABI-PROGRESS.md already contains a hand-decoded ZD2
           function, so this is the expected answer.
  * uniformly random bytes, ~8.0 bits/byte across the whole file
        -> encrypted or compressed. Custom effects become a much harder
           problem and possibly a firmware one.

This deliberately reports evidence rather than a verdict: high entropy alone
does not prove encryption (compressed data looks identical), so the section
breakdown matters more than the single number.

Usage:
    python3 build/inspect_zd2.py path/to/Effect.ZD2 [more.ZD2 ...]
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

# Signatures worth calling out if they appear anywhere in the first KB.
MAGICS = [
    (b"\x7fELF", "ELF object — same family as ZDL; disassemblable"),
    (b"PK\x03\x04", "ZIP archive — unpack it and look inside"),
    (b"\x1f\x8b", "gzip stream"),
    (b"ZD2", "literal 'ZD2' tag"),
    (b"ZDLF", "ZDL-family tag"),
]


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def describe(path: Path) -> None:
    data = path.read_bytes()
    n = len(data)
    print(f"\n=== {path.name} ({n} bytes) ===")

    print(f"  first 32 bytes: {data[:32].hex(' ')}")
    printable = sum(1 for b in data if 32 <= b < 127)
    print(f"  printable bytes: {printable * 100.0 / n:.1f}%")

    for sig, note in MAGICS:
        at = data[:1024].find(sig)
        if at >= 0:
            print(f"  FOUND {sig!r} at offset {at} — {note}")

    whole = entropy(data)
    print(f"  entropy, whole file: {whole:.2f} bits/byte  (8.00 = indistinguishable from random)")

    # Per-block entropy matters more than the total. Real code is uneven --
    # headers and tables are low, instruction streams middling. Encryption is
    # flat and high everywhere, which is the tell.
    #
    # Two things this got wrong first time round, both of which made random data
    # read as "analysable": a short TRAILING block has few samples and therefore
    # low measured entropy, which dragged the minimum down and faked unevenness;
    # and entropy measured over a small block is biased low regardless, so a
    # threshold set for the theoretical 8.0 could never fire. Blocks are now a
    # full 1024 bytes, partial tails are dropped, and the threshold is set from
    # what random data actually measures at that size (~7.8).
    block = 1024
    vals = [entropy(data[i:i + block]) for i in range(0, n - block + 1, block)]
    if len(vals) < 2:
        print(f"  file too small for a per-block read ({n} bytes; need >= {block * 2})")
    else:
        lo, hi = min(vals), max(vals)
        print(f"  per-block ({block}B, {len(vals)} blocks): min {lo:.2f}  max {hi:.2f}  spread {hi - lo:.2f}")
        if lo > 7.3:
            print("  -> FLAT AND HIGH everywhere. Consistent with encryption or compression.")
        elif hi - lo > 1.5:
            print("  -> UNEVEN. Typical of real code and data. Analysable.")
        else:
            print("  -> inconclusive; try a few more files before concluding.")

    runs = sum(1 for i in range(1, n) if data[i] == data[i - 1] == 0)
    print(f"  zero-run bytes: {runs * 100.0 / n:.1f}%  (encryption leaves almost none)")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    for a in args:
        p = Path(a)
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            continue
        describe(p)
    print("\nReport the output rather than a conclusion — the section breakdown is")
    print("what decides this, and one file is not a sample.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
