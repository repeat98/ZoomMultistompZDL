"""Rebuild and verify the release files using two local Git checkouts and a local stock comparison folder."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

kit = Path(__file__).resolve().parents[1]
manifest = json.loads((kit / "manifest.json").read_text())
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("effects_checkout", type=Path)
parser.add_argument("runtime_checkout", type=Path)
parser.add_argument("stock_dir", type=Path)
args = parser.parse_args()
stock = args.stock_dir.resolve()
tools = ("build/check_no_stock.py", "build/own_runtime.py", "build/runtime")

def unpack(repository, revision, paths, target):
    data = subprocess.check_output(["git", "-C", repository, "archive", revision, "--", *paths])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(target, filter="data")

with tempfile.TemporaryDirectory(prefix="ms70cdr-verify-") as directory:
    source = Path(directory)
    build_files = subprocess.check_output(
        ["git", "-C", args.effects_checkout, "ls-tree", "--name-only", manifest["sourceRevision"] + ":build"],
        text=True
    ).splitlines()
    sources = ["build/" + name for name in build_files if name.endswith((".py", ".asm"))]
    sources.extend(["src/airwindows/common", "src/custom/common"])
    sources.extend(effect["source"] for effect in manifest["effects"])
    unpack(args.effects_checkout, manifest["sourceRevision"], sources, source)
    unpack(args.runtime_checkout, manifest["runtimeRevision"], tools, source)
    subprocess.run(["git", "apply", kit / "build/own-runtime-linker.patch"], cwd=source, check=True)
    subprocess.run([sys.executable, kit / "build/prepare-display-guard.py", source], check=True)
    env = dict(os.environ, **manifest["flags"], PYTHONDONTWRITEBYTECODE="1")
    for effect in manifest["effects"]:
        script = source / effect["source"] / "build.py"
        subprocess.run([sys.executable, "-B", script], cwd=source, env=env, check=True)
        binary = source / "dist" / effect["file"]
        digest = hashlib.sha256(binary.read_bytes()).hexdigest()
        if digest != effect["sha256"]:
            sys.exit(f"{binary.name}: rebuilt SHA-256 {digest} differs from the release manifest")
        subprocess.run([sys.executable, "-B", source / "build/check_no_stock.py", binary,
                        "--stock-dir", stock], cwd=source, env=env, check=True)
        print(f"Verified {binary.name} {digest}", flush=True)
