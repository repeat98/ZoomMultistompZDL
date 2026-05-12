#!/usr/bin/env python3
"""Extract and disassemble a ZDL's embedded C6000 ELF.

This is a reverse-engineering helper for stock ZDLs. It writes the embedded
ELF next to the requested output prefix, runs TI `dis6x`, and prints a small
summary of `.audio` accesses rooted in the first argument register (`A4`).
Those roots are the current lead for host-provided state pointers.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from zdl import Zdl

DEFAULT_DIS6X = Path(
    "/Applications/ti/ccs2050/ccs/tools/compiler/"
    "ti-cgt-c6000_8.5.0.LTS/bin/dis6x"
)


def _audio_lines(asm_text: str) -> list[str]:
    lines: list[str] = []
    in_audio = False
    for line in asm_text.splitlines():
        if "TEXT Section .audio" in line:
            in_audio = True
            continue
        if in_audio and re.match(r"^(TEXT|DATA|BSS) Section ", line):
            break
        if in_audio:
            lines.append(line)
    return lines


def summarize_ctx_roots(asm_text: str) -> dict[int, int]:
    """Return likely ctx[word] access counts from the .audio section.

    This intentionally uses simple disassembly text heuristics. It follows
    direct register copies from A4, then counts loads/stores through those
    aliases. It is a triage aid, not a decompiler.
    """

    aliases = {"A4"}
    counts: dict[int, int] = {}
    mem_re = re.compile(r"\*(?:\+)?([AB]\d+)\[(\d+)\]")
    mv_re = re.compile(r"\bMV\.[LS]\d(?:X)?\s+A4,([AB]\d+)\b")

    for line in _audio_lines(asm_text):
        mv = mv_re.search(line)
        if mv:
            aliases.add(mv.group(1))

        for reg, slot_s in mem_re.findall(line):
            if reg in aliases:
                slot = int(slot_s)
                counts[slot] = counts.get(slot, 0) + 1

    return dict(sorted(counts.items()))


def disassemble_one(zdl_path: Path, out_dir: Path, dis6x: Path) -> None:
    zdl = Zdl.load(zdl_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = zdl_path.name
    elf_path = out_dir / f"{stem}.out"
    asm_path = out_dir / f"{stem}.asm"

    elf_path.write_bytes(zdl.elf)
    subprocess.run([str(dis6x), str(elf_path), str(asm_path)], check=True)

    asm_text = asm_path.read_text(encoding="utf-8", errors="replace")
    roots = summarize_ctx_roots(asm_text)
    roots_s = ", ".join(f"ctx[{slot}]x{count}" for slot, count in roots.items())
    print(f"{zdl_path}:")
    print(f"  elf: {elf_path}")
    print(f"  asm: {asm_path}")
    print(f"  audio ctx roots: {roots_s or '(none found)'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zdl", nargs="+", type=Path, help="ZDL file(s) to disassemble")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/tmp/zoom-zdl-dis"),
        help="directory for extracted .out/.asm files",
    )
    parser.add_argument("--dis6x", type=Path, default=DEFAULT_DIS6X)
    args = parser.parse_args()

    for zdl_path in args.zdl:
        disassemble_one(zdl_path, args.out_dir, args.dis6x)


if __name__ == "__main__":
    main()
