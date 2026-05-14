#!/usr/bin/env python3
"""Rebuild release plugins in this repo, dropping the resulting .ZDL files
into ./dist/. Point the Zoom Effect Manager at that directory.

Usage:
    python3 build_all.py             # release plugins, clean dist first
    python3 build_all.py --all       # release + diagnostic/hardware-probe plugins
    python3 build_all.py gain        # single plugin
    python3 build_all.py gain hello  # subset
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"

PLUGIN_DIR = ROOT / "src" / "airwindows"
PROBE_DIR = ROOT / "src" / "hardware_probes"

# Each entry: (display name, path to its build.py). Keep release builds clean by
# default; diagnostic/probe builds remain available by name or with --all.
RELEASE_PLUGINS = [
    ("gain",        PLUGIN_DIR / "gain"        / "build.py"),
    ("purestdrive", PLUGIN_DIR / "purestdrive" / "build.py"),
    ("tapehack",    PLUGIN_DIR / "tapehack"    / "build.py"),
    ("totape9",     PLUGIN_DIR / "totape9"     / "build.py"),
    ("stereochorus", PLUGIN_DIR / "stereochorus" / "build.py"),
]

DIAGNOSTIC_PLUGINS = [
    ("hello",       PLUGIN_DIR / "hello"       / "build.py"),
    ("ctxmap",      PROBE_DIR / "ctxmap"      / "build.py"),
    ("paramtap",    PROBE_DIR / "paramtap"    / "build.py"),
    ("ctxgate",     PROBE_DIR / "ctxgate"     / "build.py"),
    ("ctxnib",      PROBE_DIR / "ctxnib"      / "build.py"),
    ("stateping",   PROBE_DIR / "stateping"   / "build.py"),
    ("stateiso",    PROBE_DIR / "stateiso"    / "build.py"),
    ("statecomb",   PROBE_DIR / "statecomb"   / "build.py"),
    ("desccomb",    PROBE_DIR / "desccomb"    / "build.py"),
    ("descsize",    PROBE_DIR / "descsize"    / "build.py"),
    ("desciso",     PROBE_DIR / "desciso"     / "build.py"),
]

PLUGINS = RELEASE_PLUGINS + DIAGNOSTIC_PLUGINS


def main(argv: list[str]) -> int:
    DIST.mkdir(exist_ok=True)
    args = argv[1:]
    build_all = False
    selected_args: list[str] = []
    for arg in args:
        if arg == "--all":
            build_all = True
        else:
            selected_args.append(arg)

    selected = set(selected_args) if selected_args else None
    pool = PLUGINS if (build_all or selected is not None) else RELEASE_PLUGINS
    plugins = [(n, p) for n, p in pool if (selected is None or n in selected)]
    if not plugins:
        print(f"unknown plugin(s): {selected}", file=sys.stderr)
        return 1

    if selected is None and not build_all:
        for zdl in DIST.glob("*.ZDL"):
            zdl.unlink()

    failures: list[str] = []
    for name, build_py in plugins:
        print(f"\n========== {name} ==========")
        rc = subprocess.run([sys.executable, "-B", str(build_py)]).returncode
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
