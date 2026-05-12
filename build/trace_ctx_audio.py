#!/usr/bin/env python3
"""Trace first-level ctx[] pointer use in a dis6x assembly listing.

This is intentionally a lightweight text tracer, not a decompiler. It looks
inside the .audio section, tracks direct aliases of the audio callback argument
(`A4`), records loads from ctx[n], and reports later memory accesses through
the loaded registers.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


MEM_RE = re.compile(r"\*(?:\+)?([AB]\d+)\[(-?\d+)\]")
MV_ARG_RE = re.compile(r"\bMV\.[LS]\d(?:X)?\s+A4,([AB]\d+)\b")
MV_RE = re.compile(r"\bMV\.[LS]\d(?:X)?\s+([AB]\d+),([AB]\d+)\b")
LD_RE = re.compile(r"\bLD(?:N)?(?:D)?W\.[^\s]+\s+.*\*(?:\+)?([AB]\d+)\[(-?\d+)\],([AB]\d+)(?::([AB]\d+))?")
ST_RE = re.compile(r"\bST(?:N)?(?:D)?W\.[^\s]+\s+([AB]\d+)(?::([AB]\d+))?,\*(?:\+)?([AB]\d+)\[(-?\d+)\]")


@dataclass
class Access:
    line_no: int
    text: str


def audio_lines(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_audio = False
    for line_no, line in enumerate(text.splitlines(), 1):
        if "TEXT Section .audio" in line:
            in_audio = True
            continue
        if in_audio and re.match(r"^(TEXT|DATA|BSS) Section ", line):
            break
        if in_audio:
            out.append((line_no, line))
    return out


def trace(text: str) -> dict[int, list[Access]]:
    ctx_aliases = {"A4"}
    reg_roots: dict[str, int] = {}
    uses: dict[int, list[Access]] = defaultdict(list)

    for line_no, line in audio_lines(text):
        mv_arg = MV_ARG_RE.search(line)
        if mv_arg:
            ctx_aliases.add(mv_arg.group(1))

        for base, off_s in MEM_RE.findall(line):
            if base in ctx_aliases:
                slot = int(off_s)
                ld = LD_RE.search(line)
                if ld and ld.group(1) == base and int(ld.group(2)) == slot:
                    reg_roots[ld.group(3)] = slot
                    if ld.group(4):
                        reg_roots[ld.group(4)] = slot
                uses[slot].append(Access(line_no, line))

        mv = MV_RE.search(line)
        if mv and mv.group(1) in reg_roots:
            reg_roots[mv.group(2)] = reg_roots[mv.group(1)]

        for reg, slot in list(reg_roots.items()):
            if re.search(rf"\*\+?{reg}\[", line):
                # Avoid double-counting the original ctx load line.
                if not any(base == reg and int(off) == slot for base, off in MEM_RE.findall(line) if base in ctx_aliases):
                    uses[slot].append(Access(line_no, line))

    return dict(sorted(uses.items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asm", nargs="+", type=Path)
    parser.add_argument("--slots", default="2,3,13,14", help="comma-separated ctx slots to print")
    parser.add_argument("--limit", type=int, default=40, help="max accesses per slot")
    args = parser.parse_args()

    wanted = {int(x) for x in args.slots.split(",") if x.strip()}

    for asm_path in args.asm:
        print(f"\n== {asm_path} ==")
        traced = trace(asm_path.read_text(encoding="utf-8", errors="replace"))
        for slot in sorted(wanted):
            accesses = traced.get(slot, [])
            print(f"ctx[{slot}]: {len(accesses)} traced access(es)")
            for access in accesses[: args.limit]:
                print(f"  {access.line_no:5d}: {access.text}")


if __name__ == "__main__":
    main()
