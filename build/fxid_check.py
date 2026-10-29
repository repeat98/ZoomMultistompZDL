#!/usr/bin/env python3
"""Check release effect IDs against docs/FXID-REGISTRY.md.

Fails when a release effect:
  * shares gid + fxid with another release effect,
  * shares gid + fxid with a row under "IDs used by other collections",
  * is missing from the registry's release table, or
  * has a dist/ header whose gid/fxid differs from its manifest.json.

Usage: python3 -B build/fxid_check.py
"""

from __future__ import annotations

import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "docs" / "FXID-REGISTRY.md"
DIST = ROOT / "dist"
EXTERNAL_HEADING = "## IDs used by other collections"
RELEASE_HEADING = "### Release effects"


def _section_rows(text: str, heading: str) -> list[list[str]]:
    """Table rows (cells stripped) of the first table after `heading`."""
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    except StopIteration:
        raise SystemExit(f"{REGISTRY.name}: heading {heading!r} not found")
    rows: list[list[str]] = []
    for line in lines[start + 1:]:
        if line.startswith("#"):
            break
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        rows.append(cells)
    return rows[1:]  # drop the header row


def parse_ids(cell: str) -> list[int]:
    """'403, 414–416, 500-699' -> [403, 414, 415, 416, 500, ..., 699]."""
    ids: list[int] = []
    for part in cell.replace("–", "-").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            raise SystemExit(f"{REGISTRY.name}: cannot read fxid {part!r}")
        lo = int(m.group(1))
        hi = int(m.group(2) or lo)
        ids.extend(range(lo, hi + 1))
    return ids


def external_ids(text: str) -> dict[tuple[int, int], str]:
    """(gid, fxid) -> source, from the "IDs used by other collections" table."""
    out: dict[tuple[int, int], str] = {}
    for cells in _section_rows(text, EXTERNAL_HEADING):
        gid, fxids, _effects, source = cells[:4]
        for fxid in parse_ids(fxids):
            out.setdefault((int(gid), fxid), source)
    return out


def registry_release_ids(text: str) -> set[tuple[int, int]]:
    return {(int(c[1]), int(c[0])) for c in _section_rows(text, RELEASE_HEADING)}


def release_manifests() -> list[tuple[str, Path, dict]]:
    sys.path.insert(0, str(ROOT))
    from build_all import RELEASE_PLUGINS  # noqa: E402

    out = []
    for name, build_py in RELEASE_PLUGINS:
        manifest_path = build_py.parent / "manifest.json"
        out.append((name, manifest_path, json.loads(manifest_path.read_text())))
    return out


def header_ids(zdl: Path) -> tuple[int, int]:
    head = zdl.read_bytes()[:76]
    if len(head) < 76 or head[4:8] != b"SIZE":
        raise SystemExit(f"{zdl}: not a ZDL")
    return head[60], struct.unpack_from("<H", head, 64)[0]


def check() -> list[str]:
    text = REGISTRY.read_text()
    external = external_ids(text)
    listed = registry_release_ids(text)
    problems: list[str] = []
    seen: dict[tuple[int, int], str] = {}
    for name, manifest_path, m in release_manifests():
        key = (int(m["gid"]), int(m["fxid"]))
        label = f"{name} (gid {key[0]}, fxid {key[1]})"
        if key in seen:
            problems.append(f"{label} has the same ID as release effect {seen[key]}")
        seen[key] = name
        if key in external:
            problems.append(f"{label} collides with another collection: {external[key]}")
        if key not in listed:
            problems.append(f"{label} is not in the release table of {REGISTRY.name}")
        zdl = DIST / f"{m.get('output_basename', m['effect_name'])}.ZDL"
        if zdl.exists():
            got = header_ids(zdl)
            if got != key:
                problems.append(
                    f"{label}: dist/{zdl.name} header has gid {got[0]}, fxid {got[1]}; "
                    "rebuild it"
                )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("\nfxid check failed (see docs/FXID-REGISTRY.md):", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("fxid check: release IDs are unique and clear of other collections")
    return 0


if __name__ == "__main__":
    sys.exit(main())
