#!/usr/bin/env python3
"""Render desktop reference previews for ZoomMultistompZDL effects."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import soundfile as sf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

from renderers import RENDERERS  # noqa: E402


def discover_effects() -> dict[str, dict]:
    effects: dict[str, dict] = {}
    for base in (ROOT / "src" / "airwindows", ROOT / "src" / "custom"):
        for manifest_path in sorted(base.glob("*/manifest.json")):
            manifest = json.loads(manifest_path.read_text())
            key = manifest_path.parent.name.lower()
            basename = manifest.get("output_basename", manifest["effect_name"])
            # Ship-list effects must have a built ZDL, but effects that already
            # have a desktop renderer can be previewed before they are built —
            # that is the desktop-first ("hear it before you flash") workflow.
            if not (ROOT / "dist" / f"{basename}.ZDL").exists() and key not in RENDERERS:
                continue
            effects[key] = {
                "key": key,
                "manifest": manifest,
                "manifest_path": manifest_path,
                "renderer": RENDERERS.get(key),
            }
    return effects


def parse_overrides(raw: list[str]) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"expected NAME=VALUE, got {item!r}")
        name, value = item.split("=", 1)
        values[name.lower()] = float(value)
    return values


def default_params(effect: dict) -> dict[str, float]:
    return {
        param["name"].lower(): float(param["default"])
        for param in effect["manifest"]["params"]
    }


def print_effects(effects: dict[str, dict]) -> None:
    print("Desktop audio preview coverage:\n")
    for key, effect in sorted(effects.items()):
        status = "ready" if effect["renderer"] else "adapter needed"
        name = effect["manifest"]["effect_name"]
        params = ", ".join(p["name"] for p in effect["manifest"]["params"])
        print(f"  {key:<14} {status:<14} {name:<14} [{params}]")


def render(effect: dict, input_path: Path, output_path: Path,
           overrides: dict[str, float], tail: float) -> None:
    renderer = effect["renderer"]
    if renderer is None:
        raise ValueError(
            f"{effect['key']!r} has no desktop renderer yet. "
            "Run `preview.py list` to inspect coverage."
        )

    audio, sample_rate = sf.read(str(input_path), always_2d=True, dtype="float64")
    params = default_params(effect)
    unknown = sorted(set(overrides) - set(params))
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(unknown)}")
    params.update(overrides)

    print(f"[{effect['key']}] {input_path.name} -> {output_path.name}")
    print("  " + ", ".join(f"{name}={value:g}" for name, value in params.items()))
    rendered = renderer(audio, sample_rate, params, tail, ROOT)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), rendered, sample_rate, subtype="PCM_24")
    print(f"  wrote {len(rendered) / sample_rate:.3f} s -> {output_path}")


def main() -> None:
    effects = discover_effects()
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show effects and desktop-adapter coverage")

    render_ap = sub.add_parser("render", help="render one effect")
    render_ap.add_argument("effect", choices=sorted(effects))
    render_ap.add_argument("input", type=Path)
    render_ap.add_argument("output", type=Path)
    render_ap.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    render_ap.add_argument("--tail", type=float, default=5.0)

    all_ap = sub.add_parser("render-all", help="render every supported effect")
    all_ap.add_argument("input", type=Path)
    all_ap.add_argument("output_dir", type=Path)
    all_ap.add_argument("--tail", type=float, default=5.0)

    args = ap.parse_args()
    if args.command == "list":
        print_effects(effects)
        return

    if args.command == "render":
        render(effects[args.effect], args.input, args.output,
               parse_overrides(args.set), args.tail)
        return

    for key, effect in sorted(effects.items()):
        if effect["renderer"] is None:
            continue
        output = args.output_dir / f"{args.input.stem}_{key}.wav"
        render(effect, args.input, output, {}, args.tail)


if __name__ == "__main__":
    main()
