#!/usr/bin/env python3
"""Summarize ctx-rooted struct fields in stock ZDL audio assembly.

`trace_ctx_audio.py` reports raw lines. This helper keeps a tiny symbolic
model of registers loaded from `ctx[n]`, follows simple register moves and
constant adds, then prints field offsets touched through each derived base.
It is deliberately conservative and meant for reverse-engineering notes, not
for recompilation.
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


MEM_RE = re.compile(r"\*(?:\+)?([AB]\d+)\[(-?\d+)\]")
MV_ARG_RE = re.compile(r"\bMV\.[LS]\d(?:X)?\s+A4,([AB]\d+)\b")
MV_RE = re.compile(r"\bMV\.[LSD]\d(?:X)?\s+([AB]\d+),([AB]\d+)\b")
LDW_RE = re.compile(
    r"\bLD(?:N)?(?:D)?W\.[^\s]+\s+.*\*(?:\+)?([AB]\d+)\[(-?\d+)\],"
    r"([AB]\d+)(?::([AB]\d+))?"
)
IMM = r"-?(?:0x[0-9a-fA-F]+|[0-9]+)"
ADD_BYTE_RE = re.compile(rf"\bADD(?:K)?\.[LSDA]\d(?:X)?\s+([AB]\d+),({IMM}),([AB]\d+)\b")
ADDAW_RE = re.compile(rf"\bADDAW\.[DLS]\d(?:X)?\s+([AB]\d+),({IMM}),([AB]\d+)\b")
ADDAD_RE = re.compile(rf"\bADDAD\.[DLS]\d(?:X)?\s+([AB]\d+),({IMM}),([AB]\d+)\b")


@dataclass(frozen=True)
class Root:
    slot: int
    byte_offset: int = 0

    def label(self) -> str:
        if self.byte_offset == 0:
            return f"ctx[{self.slot}]"
        sign = "+" if self.byte_offset >= 0 else "-"
        return f"ctx[{self.slot}]{sign}0x{abs(self.byte_offset):x}"


def parse_int(value: str) -> int:
    return int(value, 0)


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


def trace(text: str) -> dict[Root, dict[int, list[str]]]:
    ctx_aliases = {"A4"}
    roots: dict[str, Root] = {}
    fields: dict[Root, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))

    for line_no, line in audio_lines(text):
        mv_arg = MV_ARG_RE.search(line)
        if mv_arg:
            ctx_aliases.add(mv_arg.group(1))

        ld = LDW_RE.search(line)
        if ld and ld.group(1) in ctx_aliases:
            slot = int(ld.group(2))
            roots[ld.group(3)] = Root(slot)
            if ld.group(4):
                roots[ld.group(4)] = Root(slot)

        mv = MV_RE.search(line)
        if mv and mv.group(1) in roots:
            roots[mv.group(2)] = roots[mv.group(1)]

        for regex, scale in ((ADD_BYTE_RE, 1), (ADDAW_RE, 4), (ADDAD_RE, 8)):
            add = regex.search(line)
            if add and add.group(1) in roots:
                roots[add.group(3)] = Root(
                    roots[add.group(1)].slot,
                    roots[add.group(1)].byte_offset + parse_int(add.group(2)) * scale,
                )

        for base, field_s in MEM_RE.findall(line):
            root = roots.get(base)
            if root is None:
                continue
            field = int(field_s)
            fields[root][field].append(f"{line_no}: {line.strip()}")

    return dict(sorted(fields.items(), key=lambda item: (item[0].slot, item[0].byte_offset)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asm", nargs="+", type=Path)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    for asm_path in args.asm:
        print(f"\n== {asm_path} ==")
        traced = trace(asm_path.read_text(encoding="utf-8", errors="replace"))
        for root, root_fields in traced.items():
            field_list = ", ".join(str(field) for field in sorted(root_fields))
            print(f"{root.label()}: fields [{field_list}]")
            for field in sorted(root_fields):
                for example in root_fields[field][: args.limit]:
                    print(f"  [{field}] {example}")


if __name__ == "__main__":
    main()
