#!/usr/bin/env python3
"""Write dist/index.json: every effect in dist/ with what the Patch Editor's
installer checks before it writes to a pedal (file name, effect ID, version,
size, SHA-256). Run after changing anything in dist/.

    python3 build/dist_index.py            write it
    python3 build/dist_index.py --check    fail if it is out of date
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
DB = ROOT / "tools" / "effects_db.json"


def entries():
    names = {}
    try:
        for e in json.loads(DB.read_text())["custom"]:
            names.setdefault((e["gid"], e["fxid"]), e["name"])
    except (OSError, KeyError, ValueError):
        pass
    # Published effects only: files tracked in git (your own NAM/cab files in dist/ are ignored).
    tracked = subprocess.run(["git", "ls-files", "dist"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    out = []
    for path in sorted((ROOT / t for t in tracked), key=lambda p: p.name.upper()):
        if path.parent != DIST or path.suffix.upper() != ".ZDL" or not path.is_file():
            continue
        data = path.read_bytes()
        if data[4:8] != b"SIZE" or data[0x4C:0x50] != b"\x7fELF":
            raise SystemExit(f"{path.name}: not a ZDL")
        gid, fxid = data[0x3C], data[0x40] | data[0x41] << 8
        out.append({
            "file": path.name,
            "name": names.get((gid, fxid), path.stem),
            "gid": gid,
            "fxid": fxid,
            "version": data[0x44:0x48].decode("ascii", "replace"),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    return out


def main(argv):
    text = json.dumps({"effects": entries()}, indent=1) + "\n"
    target = DIST / "index.json"
    if "--check" in argv:
        if not target.exists() or target.read_text() != text:
            print("dist/index.json is out of date: run python3 build/dist_index.py")
            return 1
        print("dist/index.json is current")
        return 0
    target.write_text(text)
    print(f"dist/index.json: {text.count('\"file\"')} effects")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
