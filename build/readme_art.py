#!/usr/bin/env python3
"""What the README shows, and where each picture comes from.

Shared by make_gallery_png.py (one PNG per effect) and make_thumb_png.py (the
overview of every effect), so the two cannot list different effects.

Three kinds of card, all a 128x64 bitmap in the end:
  - cover: the on-device cover decoded from the built dist/<name>.ZDL;
  - live:  a frame of an animated screen (Loop, Scope, ...), run on the host
           with zvis_host.py and a test signal; their stored cover is only the
           boot screen;
  - named: a NAM or CAB loader cover with an example name and icon, drawn by
           capture_art.py exactly as the loader draws it. No capture needed.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

# The release pack, in the README's order.
PACK = ["Microlm", "Flower", "Shatter", "Arrakis", "Corrupt", "Klang", "GenLoss", "Scorch",
        "Howl", "Galactic", "Oxide", "Spool", "Taffy", "Dissolve", "Mangle", "Rooms",
        "Hydra", "Spiral", "Stasis", "Dustbox", "Rewire", "Gyre"]

# Experimental: live screens (MS-70CDR 2.10) and Tonic. name -> zvis_host args.
LIVE = {
    "Loop": ["--signal", "pluck", "--seconds", "6", "--presses", "0.3,3.3"],
    "Scope": ["--signal", "@guitar", "--seconds", "6", "--knobs", "30,12,0"],
    "Spectrum": ["--signal", "@guitar", "--seconds", "6"],
    "Ring": ["--signal", "@guitar", "--seconds", "6"],
    "Skull": ["--signal", "@guitar", "--seconds", "6"],
}
EXPERIMENTAL = ["Loop", "Scope", "Spectrum", "Ring", "Skull", "Tonic"]

# Loader examples: (gallery file stem, kind, name, icon)
EXAMPLES = [("nam-example", "NAM", "smokey", "amp"), ("cab-example", "IR", "4x12", "cabinet")]

# Luca Matturro's pack (dist/matujuice/), credited separately.
MATUJUICE = ["WaveFold", "DualShft", "Choral", "EuGate", "DubSiren", "SGNL",
             "Scrub", "GridDly", "SyncEQ", "Breather", "DirtBox", "Sweep"]


def _guitar_like(path: Path, seconds: float = 8.0) -> Path:
    """A synthetic, guitar-ish test signal (plucked notes with harmonics, a
    little noise): no recording in the repo, and the same picture every run."""
    sr = 44100
    t = np.arange(int(seconds * sr)) / sr
    rng = np.random.default_rng(7)
    notes = [82.4, 110.0, 146.8, 196.0, 123.5, 164.8, 98.0, 220.0]
    x = np.zeros_like(t)
    step = 0.375
    for k in range(int(seconds / step)):
        f = notes[k % len(notes)]
        s = int(k * step * sr)
        tt = t[s:] - t[s]
        env = np.exp(-tt * 3.2)
        x[s:] += env * sum(np.sin(2 * np.pi * f * h * tt) / h ** 1.3 for h in range(1, 7))
    x = np.tanh(5 * x / np.abs(x).max())       # overdriven, like the amp in front of these
    x += rng.normal(0, 0.02, len(x))
    x = 0.6 * x / np.abs(x).max()
    x.astype(np.float32).tofile(path)
    return path


def live_bits(name: str) -> np.ndarray:
    """The last frame an animated effect publishes, as a 64x128 bool array."""
    from PIL import Image
    eff = ROOT / "src" / "custom" / name.lower()
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        args = [a if a != "@guitar" else str(_guitar_like(td / "guitar.f32")) for a in LIVE[name]]
        subprocess.run([sys.executable, str(ROOT / "src/custom/common/zvis_host.py"), str(eff), str(td / "f"),
                        "--frames", "1", "--arena-kb", "700", *args], check=True, capture_output=True)
        png = next((td / "f").glob("*.png"))
        a = np.asarray(Image.open(png).convert("L"))
    h, w = a.shape          # zvis_host saves ink black on grey, stretched; sample pixel centres
    ys = ((np.arange(64) + 0.5) * h / 64).astype(int)
    xs = ((np.arange(128) + 0.5) * w / 128).astype(int)
    return a[ys][:, xs] < 110


def cover_bits(zdl: Path) -> np.ndarray:
    from decode_picture import decode_picture
    rows, _ = decode_picture(str(zdl))
    return np.array(rows, dtype=bool)


def named_bits(kind: str, name: str, icon: str) -> np.ndarray:
    import capture_art
    return np.array(capture_art.named_canvas(kind, name, icon).pixels, dtype=bool)


def bits_for(name: str) -> np.ndarray:
    """Bitmap for any README entry: an effect name or an EXAMPLES stem."""
    for stem, kind, nm, icon in EXAMPLES:
        if name == stem:
            return named_bits(kind, nm, icon)
    if name in LIVE:
        return live_bits(name)
    zdl = ROOT / "dist" / f"{name}.ZDL"
    if not zdl.exists():
        raise SystemExit(f"{zdl.relative_to(ROOT)} missing -- build it first")
    return cover_bits(zdl)


def to_image(bits: np.ndarray, size, bg, lit):
    from PIL import Image
    img = Image.new("RGB", (bits.shape[1], bits.shape[0]), bg)
    px = img.load()
    for y, x in zip(*np.nonzero(bits)):
        px[int(x), int(y)] = lit
    return img.resize(size, Image.NEAREST)
