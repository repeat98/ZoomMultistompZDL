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
import json
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
    ("tapeecho4",   PLUGIN_DIR / "tapeecho4"   / "build.py"),
    ("totape9",     PLUGIN_DIR / "totape9"     / "build.py"),
    ("galactic",    PLUGIN_DIR / "galactic"    / "build.py"),
    ("flower",      CUSTOM_DIR / "flower"      / "build.py"),
    ("shatter",     CUSTOM_DIR / "shatter"     / "build.py"),
    ("arrakis",     CUSTOM_DIR / "arrakis"     / "build.py"),
    ("microloom",   CUSTOM_DIR / "microloom"   / "build.py"),
    ("corrupt",     CUSTOM_DIR / "corrupt"     / "build.py"),
    ("klang",       CUSTOM_DIR / "klang"       / "build.py"),
    ("genloss",     CUSTOM_DIR / "genloss"     / "build.py"),
    ("scorch",      CUSTOM_DIR / "scorch"      / "build.py"),
    ("howl",        CUSTOM_DIR / "howl"        / "build.py"),
    ("taffy",       CUSTOM_DIR / "taffy"       / "build.py"),
    ("dissolve",    CUSTOM_DIR / "dissolve"    / "build.py"),
    ("mangle",      CUSTOM_DIR / "mangle"      / "build.py"),
    ("rooms",       CUSTOM_DIR / "rooms"       / "build.py"),
    ("hydra",       CUSTOM_DIR / "hydra"       / "build.py"),
    ("rewire",     CUSTOM_DIR / "rewire"     / "build.py"),
    ("dustbox",    CUSTOM_DIR / "dustbox"    / "build.py"),
    ("stasis",     CUSTOM_DIR / "stasis"     / "build.py"),
    ("spiral",      CUSTOM_DIR / "spiral"      / "build.py"),
    ("gyre",        CUSTOM_DIR / "gyre"        / "build.py"),
]

# Dropped from the release set 2026-06-29 after hardware listening (user
# verdict: "doesn't really do anything" / redundant): ott, reel, tapehack,
# stereochorus (Lush), verbtiny (Room). Sources kept for reference.

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
    ("ctxwatch",    PROBE_DIR / "ctxwatch"    / "build.py"),
    ("edgewatch",   PROBE_DIR / "edgewatch"   / "build.py"),
    ("matprobe",    PROBE_DIR / "matprobe"    / "build.py"),
]

# Explicit builds only until hardware listening confirms these effects.
EXPERIMENTAL_PLUGINS = [("tonic", CUSTOM_DIR / "tonic" / "build.py")]
PLUGINS = RELEASE_PLUGINS + DIAGNOSTIC_PLUGINS + EXPERIMENTAL_PLUGINS


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
    # A probe in dist/ is a shipping bug, not an inconvenience: the install docs
    # tell people to point Zoom Effect Manager at dist/ and add what they find,
    # so a stray diagnostic ends up on a stranger's pedal beeping at them.
    # EdgeWatch reached dist/ exactly that way.
    # Anything that is not a RELEASE plugin is a diagnostic and must not ship.
    probe_stems = set()
    for nm, bp in DIAGNOSTIC_PLUGINS:
        for mf in (bp.parent / "manifest_pedal.json", bp.parent / "manifest.json"):
            if mf.exists():
                try:
                    probe_stems.add(json.loads(mf.read_text()).get("effect_name", nm))
                except Exception:
                    probe_stems.add(nm)
                break
    strays = sorted(z for z in DIST.glob("*.ZDL") if z.stem in probe_stems)
    probe_check_rc = 0
    if strays:
        probe_check_rc = 1
        print("\nHARDWARE PROBES LEFT IN dist/ -- these must not ship:", file=sys.stderr)
        for z in strays:
            print(f"  {z.name}", file=sys.stderr)
        print("  move them to build/probes/ before releasing.", file=sys.stderr)

    # Always run, not just on a full build: the >8-char rule would have caught
    # EdgeWatch on the single-plugin build that leaked it.
    name_check_rc = check_dist_filenames()
    if failures:
        print(f"\nFAILED: {failures}")
        return 1

    # Re-extract the effect database into the patch editor.
    #
    # This used to be a separate step somebody had to remember, and twice it was
    # not remembered: the editor shipped Rewire without its Shift knob after the
    # shifter was added, and again with Rewire's old Bits/Ring defaults after they
    # were changed. Both times the ZDL on disk was correct and the editor's inline
    # copy silently was not, which is invisible until you go looking for a knob
    # that is not there. A build that changes an effect should update the tool that
    # drives it, in the same pass.
    db_rc = 0
    try:
        db_rc = subprocess.call([sys.executable, str(ROOT / "build" / "extract_effect_db.py")])
        if db_rc:
            print("\neffect DB sync FAILED -- the patch editor is now stale", file=sys.stderr)
    except Exception as exc:                       # pragma: no cover
        db_rc = 1
        print(f"\neffect DB sync could not run: {exc}", file=sys.stderr)

    # Effect Manager loads these same-name PNGs alongside folder ZDLs.
    thumb_rc = subprocess.call([sys.executable, str(ROOT / "build" / "make_em_thumbnails.py")])
    return name_check_rc or probe_check_rc or db_rc or thumb_rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
