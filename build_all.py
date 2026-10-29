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
PROBE_OUT = ROOT / "build" / "probes"

PLUGIN_DIR = ROOT / "src" / "airwindows"
CUSTOM_DIR = ROOT / "src" / "custom"
PROBE_DIR = ROOT / "src" / "hardware_probes"

# Each entry: (display name, path to its build.py). Keep release builds clean by
# default; diagnostic/probe builds remain available by name or with --all.
RELEASE_PLUGINS = [
    ("gain",        PLUGIN_DIR / "gain"        / "build.py"),
    ("purestdrive", PLUGIN_DIR / "purestdrive" / "build.py"),
    ("tapehack",    PLUGIN_DIR / "tapehack"    / "build.py"),
    ("tapeecho4",   PLUGIN_DIR / "tapeecho4"   / "build.py"),
    ("totape9",     PLUGIN_DIR / "totape9"     / "build.py"),
    ("stereochorus", PLUGIN_DIR / "stereochorus" / "build.py"),
    ("verbtiny",    PLUGIN_DIR / "verbtiny"    / "build.py"),
    ("galactic",    PLUGIN_DIR / "galactic"    / "build.py"),
    ("ott",         CUSTOM_DIR / "ott"         / "build.py"),
]

DIAGNOSTIC_PLUGINS = [
    ("tovinyl4",    PLUGIN_DIR / "tovinyl4"    / "build.py"),
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
    ("initprobe",   PROBE_DIR / "initprobe"   / "build.py"),
]

PLUGINS = RELEASE_PLUGINS + DIAGNOSTIC_PLUGINS


def check_dist_filenames() -> int:
    """Reject release names that can collide after Zoom's 8-char truncation."""
    by_trimmed: dict[str, list[Path]] = {}
    too_long: list[Path] = []
    for zdl in sorted(DIST.glob("*.ZDL")):
        stem = zdl.stem
        if len(stem) > 8:
            too_long.append(zdl)
        by_trimmed.setdefault(stem[:8].upper(), []).append(zdl)

    rc = 0
    if too_long:
        rc = 1
        print("\nUnsafe ZDL basenames (>8 chars; Zoom may truncate these):", file=sys.stderr)
        for zdl in too_long:
            print(f"  {zdl.name}", file=sys.stderr)

    collisions = {k: v for k, v in by_trimmed.items() if len(v) > 1}
    if collisions:
        rc = 1
        print("\nUnsafe ZDL basename collisions after 8-char truncation:", file=sys.stderr)
        for key, paths in sorted(collisions.items()):
            names = ", ".join(p.name for p in paths)
            print(f"  {key}: {names}", file=sys.stderr)

    return rc


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

    release_names = {name for name, _ in RELEASE_PLUGINS}
    failures: list[str] = []
    moved_probes: list[Path] = []
    for name, build_py in plugins:
        print(f"\n========== {name} ==========")
        before = {p.name: p.stat().st_mtime_ns for p in DIST.glob("*.ZDL")}
        rc = subprocess.run([sys.executable, "-B", str(build_py)]).returncode
        if rc != 0:
            failures.append(name)
            continue
        if name not in release_names:
            PROBE_OUT.mkdir(parents=True, exist_ok=True)
            for zdl in sorted(DIST.glob("*.ZDL")):
                old_mtime = before.get(zdl.name)
                if old_mtime is not None and old_mtime == zdl.stat().st_mtime_ns:
                    continue
                target = PROBE_OUT / zdl.name
                zdl.replace(target)
                moved_probes.append(target)

    print("\n========== summary ==========")
    print(f"output dir: {DIST}")
    for f in sorted(DIST.glob("*.ZDL")):
        print(f"  {f.name:<20} {f.stat().st_size:>6} bytes")
    if moved_probes:
        print(f"\nprobe output dir: {PROBE_OUT}")
        for f in moved_probes:
            print(f"  {f.name:<20} {f.stat().st_size:>6} bytes")
    name_check_rc = 0
    if selected is None:
        name_check_rc = check_dist_filenames()
        name_check_rc |= subprocess.run(
            [sys.executable, "-B", str(ROOT / "build" / "fxid_check.py")]).returncode
    if failures:
        print(f"\nFAILED: {failures}")
        return 1
    return name_check_rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
