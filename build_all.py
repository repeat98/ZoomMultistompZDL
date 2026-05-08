#!/usr/bin/env python3
"""Rebuild every plugin in this repo, dropping the resulting .ZDL files
into ./dist/.  Point the Zoom Effect Manager at that directory.

Usage:
    python3 build_all.py            # all plugins
    python3 build_all.py gain       # single plugin
    python3 build_all.py gain hello # subset
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

# Each entry: (display name, path to its build.py).  Keep ordered so the
# linker module gets the same exercise across runs.
PLUGINS = [
    ("hello",       ROOT / "hello"       / "build.py"),
    ("gain",        ROOT / "gain"        / "build.py"),
    ("purestdrive", ROOT / "purestdrive" / "build.py"),
]


def main(argv: list[str]) -> int:
    DIST.mkdir(exist_ok=True)
    selected = set(argv[1:]) if len(argv) > 1 else None
    plugins = [(n, p) for n, p in PLUGINS if (selected is None or n in selected)]
    if not plugins:
        print(f"unknown plugin(s): {selected}", file=sys.stderr)
        return 1

    failures: list[str] = []
    for name, build_py in plugins:
        print(f"\n========== {name} ==========")
        rc = subprocess.run([sys.executable, str(build_py)]).returncode
        if rc != 0:
            failures.append(name)

    print("\n========== summary ==========")
    print(f"output dir: {DIST}")
    for f in sorted(DIST.glob("*.ZDL")):
        print(f"  {f.name:<20} {f.stat().st_size:>6} bytes")
    if failures:
        print(f"\nFAILED: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
