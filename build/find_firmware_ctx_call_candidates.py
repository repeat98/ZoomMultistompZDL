#!/usr/bin/env python3
"""Find firmware routines that build ctx-like call frames.

This is a text heuristic for TI `dis6x` listings. It scans for indirect
branches/calls, then reports nearby stores to small word offsets on the same
base register. The useful hits are functions that populate a structure and
then call through a function pointer; the noisy hits are stack frames,
interrupt save/restore code, and coroutine trampolines.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


LINE_RE = re.compile(r"^\s*([0-9a-f]{8})\s+")
INDIRECT_RE = re.compile(r"\b(?:B|CALLP)\.S[12]X?\s+([AB]\d+)\b")
STORE_RE = re.compile(
    r"\bST(?:N)?(?:D)?W\.[^\s]+\s+([^,]+),\*(?:\+)?([AB]\d+)\[(-?\d+)\]"
)
LOAD_RE = re.compile(
    r"\bLD(?:N)?(?:D)?W\.[^\s]+\s+\*(?:\+)?([AB]\d+)\[(-?\d+)\],"
    r"([AB]\d+)(?::([AB]\d+))?"
)
MVC_RE = re.compile(r"\bMVC\.S[12]")

INTERESTING_SLOTS = {1, 2, 3, 4, 5, 6, 11, 12, 13, 14}


@dataclass(frozen=True)
class AsmLine:
    line_no: int
    addr: str
    text: str


@dataclass
class Candidate:
    branch: AsmLine
    target_reg: str
    base_reg: str
    slots: set[int]
    stores: list[AsmLine]
    target_loads: list[AsmLine]
    score: int


def parse_lines(path: Path) -> list[AsmLine]:
    lines: list[AsmLine] = []
    for line_no, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = LINE_RE.match(text)
        if match:
            lines.append(AsmLine(line_no, match.group(1), text))
    return lines


def score_candidate(slots: set[int], stores: list[AsmLine], target_loads: list[AsmLine]) -> int:
    score = len(slots & INTERESTING_SLOTS) * 10 + len(slots)
    if {2, 3}.issubset(slots):
        score += 25
    if {11, 12}.issubset(slots):
        score += 15
    if {13, 14}.issubset(slots):
        score += 15
    if target_loads:
        score += 20
    if any(MVC_RE.search(line.text) for line in stores):
        score -= 20
    return score


def find_candidates(lines: list[AsmLine], window: int) -> list[Candidate]:
    candidates: list[Candidate] = []

    for idx, line in enumerate(lines):
        indirect = INDIRECT_RE.search(line.text)
        if not indirect:
            continue

        target_reg = indirect.group(1)
        start = max(0, idx - window)
        prior = lines[start:idx]
        stores_by_base: dict[str, list[tuple[int, AsmLine]]] = defaultdict(list)
        target_loads: list[AsmLine] = []

        for prior_line in prior:
            store = STORE_RE.search(prior_line.text)
            if store:
                slot = int(store.group(3))
                if 0 <= slot <= 20:
                    stores_by_base[store.group(2)].append((slot, prior_line))

            load = LOAD_RE.search(prior_line.text)
            if load and target_reg in {load.group(3), load.group(4)}:
                target_loads.append(prior_line)

        for base_reg, base_stores in stores_by_base.items():
            slots = {slot for slot, _ in base_stores}
            if len(slots & INTERESTING_SLOTS) < 2:
                continue

            store_lines = [store_line for _, store_line in base_stores]
            score = score_candidate(slots, store_lines, target_loads)
            candidates.append(
                Candidate(
                    branch=line,
                    target_reg=target_reg,
                    base_reg=base_reg,
                    slots=slots,
                    stores=store_lines,
                    target_loads=target_loads,
                    score=score,
                )
            )

    return sorted(candidates, key=lambda c: (-c.score, c.branch.line_no, c.base_reg))


def print_candidate(candidate: Candidate, limit: int) -> None:
    slots = ",".join(str(slot) for slot in sorted(candidate.slots))
    print(
        f"{candidate.branch.addr} line {candidate.branch.line_no}: "
        f"{candidate.branch.text.strip()}"
    )
    print(
        f"  base={candidate.base_reg} slots=[{slots}] "
        f"target={candidate.target_reg} score={candidate.score}"
    )

    if candidate.target_loads:
        print("  target loads:")
        for line in candidate.target_loads[-limit:]:
            print(f"    {line.line_no:6d} {line.text}")

    print("  nearby stores:")
    for line in candidate.stores[-limit:]:
        print(f"    {line.line_no:6d} {line.text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disasm", type=Path)
    parser.add_argument("--window", type=int, default=120)
    parser.add_argument("--min-score", type=int, default=35)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-candidates", type=int, default=60)
    args = parser.parse_args()

    lines = parse_lines(args.disasm)
    candidates = [
        candidate
        for candidate in find_candidates(lines, args.window)
        if candidate.score >= args.min_score
    ]

    print(f"{args.disasm}: {len(candidates)} candidate(s)")
    for candidate in candidates[: args.max_candidates]:
        print()
        print_candidate(candidate, args.limit)


if __name__ == "__main__":
    main()
