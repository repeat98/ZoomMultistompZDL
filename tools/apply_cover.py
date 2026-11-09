#!/usr/bin/env python3
"""Apply a hand-drawn cover from tools/cover_editor.html to its effect, in one step.

The cover editor exports a JSON like {"name":"Mangle","grid":[[...]]}. Normally
you'd have to move that file to src/airwindows/common/covers/<Name>.json by hand
and then rebuild the effect. This does both.

    python3 tools/apply_cover.py                 # newest cover JSON in ~/Downloads
    python3 tools/apply_cover.py Mangle.json      # a specific file
    python3 tools/apply_cover.py --place-only     # copy into place, skip the rebuild

It reads the effect name from the JSON, drops the file at covers/<Name>.json, finds
that effect's build directory, and runs `build_all.py <dir>` to bake the cover into
dist/<Name>.ZDL. Flash that .ZDL with Zoom Effect Manager and every patch using the
effect shows your art.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERS = ROOT / "src" / "airwindows" / "common" / "covers"
DOWNLOADS = Path.home() / "Downloads"


def _manifest_index():
    """effect_name -> build directory basename (the build_all.py target key)."""
    idx = {}
    for mf in ROOT.glob("src/*/*/manifest_pedal.json"):
        try:
            nm = json.loads(mf.read_text()).get("effect_name")
        except Exception:
            continue
        if nm:
            idx[nm] = mf.parent.name
    # fall back to plain manifest.json for effects that only ship one
    for mf in ROOT.glob("src/*/*/manifest.json"):
        try:
            nm = json.loads(mf.read_text()).get("effect_name")
        except Exception:
            continue
        if nm and nm not in idx:
            idx[nm] = mf.parent.name
    return idx


def _pick_json(args):
    files = [a for a in args if not a.startswith("-")]
    if files:
        p = Path(files[0]).expanduser()
        if not p.exists() and (DOWNLOADS / files[0]).exists():
            p = DOWNLOADS / files[0]
        return p
    # newest cover-shaped JSON in ~/Downloads
    cands = []
    for p in DOWNLOADS.glob("*.json"):
        try:
            if "grid" in json.loads(p.read_text()):
                cands.append(p)
        except Exception:
            pass
    if not cands:
        sys.exit(f"No cover JSON found in {DOWNLOADS}. Download one from the cover "
                 f"editor first, or pass a path.")
    return max(cands, key=lambda p: p.stat().st_mtime)


def apply_cover(name: str, grid, build: bool = True) -> dict:
    """Write covers/<name>.json and (optionally) rebuild that effect's .ZDL.

    Reusable by the CLI and the editor's build server. Returns a dict:
    {ok, message, log, zdl, target}. Never raises for expected failures
    (unknown effect / build error) — those come back as ok=False.
    """
    idx = _manifest_index()
    if name not in idx:
        return {"ok": False, "message": f"'{name}' isn't a known effect.",
                "log": "", "zdl": None, "target": None}
    if not isinstance(grid, list) or not grid:
        return {"ok": False, "message": "cover grid is empty.",
                "log": "", "zdl": None, "target": idx[name]}

    COVERS.mkdir(parents=True, exist_ok=True)
    dst = COVERS / f"{name}.json"
    dst.write_text(json.dumps({"name": name, "w": 128, "h": 64, "grid": grid}))
    target = idx[name]
    if not build:
        return {"ok": True, "message": f"cover saved ({dst.relative_to(ROOT)})",
                "log": "", "zdl": None, "target": target}

    r = subprocess.run([sys.executable, "build_all.py", target], cwd=ROOT,
                       capture_output=True, text=True)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        return {"ok": False, "message": f"build failed for {target}",
                "log": log[-4000:], "zdl": None, "target": target}

    # The Patch Editor draws covers from the effect DB baked INTO its HTML, not from
    # the pedal — so a rebuilt .ZDL shows the new art on the hardware while PE keeps
    # displaying the old one until the DB is regenerated. Do it here so the two can
    # never drift apart. (Hard-reload PE afterwards to pick it up.)
    r2 = subprocess.run([sys.executable, "build/extract_effect_db.py"], cwd=ROOT,
                        capture_output=True, text=True)
    log += (r2.stdout or "") + (r2.stderr or "")
    if r2.returncode != 0:
        return {"ok": False,
                "message": f"built dist/{name}.ZDL but the effect DB refresh failed — "
                           f"PE will still show the old cover",
                "log": log[-4000:], "zdl": f"dist/{name}.ZDL", "target": target}

    zdl = f"dist/{name}.ZDL"
    return {"ok": True, "message": f"built {zdl} + refreshed PE's cover DB",
            "log": log[-4000:], "zdl": zdl, "target": target}


def main() -> None:
    args = sys.argv[1:]
    place_only = "--place-only" in args or "--no-build" in args
    src = _pick_json(args)

    try:
        data = json.loads(src.read_text())
    except Exception as exc:
        sys.exit(f"{src.name}: not valid JSON ({exc})")
    if "grid" not in data:
        sys.exit(f"{src.name}: no 'grid' — not a cover JSON.")

    name = data.get("name") or src.stem
    idx = _manifest_index()
    if name not in idx:
        known = ", ".join(sorted(idx))
        sys.exit(f"'{name}' isn't a known effect (from {src.name}). Re-export with the "
                 f"effect picked in the editor's dropdown.\nKnown effects: {known}")

    print(f"→ {'placing' if place_only else 'building'} {name} …")
    res = apply_cover(name, data["grid"], build=not place_only)
    if res["log"]:
        print(res["log"].rstrip())
    if not res["ok"]:
        sys.exit(f"✗ {res['message']} — cover is in place; fix and re-run "
                 f"`python3 build_all.py {res['target']}`.")
    print(f"✓ {res['message']}")
    if res["zdl"]:
        print(f"  Flash it with Zoom Effect Manager; patches using {name} now show your cover.")
    elif place_only:
        print(f"  (skipped rebuild) run:  python3 build_all.py {res['target']}")


if __name__ == "__main__":
    main()
