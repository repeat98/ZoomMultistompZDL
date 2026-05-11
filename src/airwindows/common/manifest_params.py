"""Helpers for turning manifest params into linker/C metadata."""

from __future__ import annotations

import re
from pathlib import Path


def c_ident(text: str) -> str:
    ident = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_").upper()
    if not ident or ident[0].isdigit():
        ident = f"P_{ident}"
    return ident


def c_float(value: float) -> str:
    text = f"{float(value):.9g}"
    if "e" not in text and "." not in text:
        text += ".0"
    return f"{text}f"


def write_param_header(manifest: dict, out_path: str | Path, prefix: str) -> None:
    """Write C defines for manifest param slots, defaults, and audio ranges."""
    lines = [
        "/* Generated from manifest.json. Do not edit by hand. */",
        f"#ifndef {prefix}_PARAMS_H",
        f"#define {prefix}_PARAMS_H",
        "",
        f"#define {prefix}_PARAM_COUNT {len(manifest['params'])}",
    ]
    for idx, p in enumerate(manifest["params"]):
        name = c_ident(p["name"])
        kind = p.get("type", p.get("kind", "knob"))
        max_val = int(p.get("max", 1 if kind == "switch" else 100))
        default_val = int(p.get("default", 0))
        if "audio_default" in p:
            default_norm = float(p["audio_default"])
        elif max_val > int(p.get("min", 0)):
            default_norm = (default_val - int(p.get("min", 0))) / float(max_val - int(p.get("min", 0)))
        else:
            default_norm = 0.0
        lines.extend([
            "",
            f"#define {prefix}_{name}_INDEX {idx}",
            f"#define {prefix}_{name}_SLOT {idx + 5}",
            f"#define {prefix}_{name}_TYPE_{c_ident(kind)} 1",
            f"#define {prefix}_{name}_UI_MIN {int(p.get('min', 0))}",
            f"#define {prefix}_{name}_UI_MAX {max_val}",
            f"#define {prefix}_{name}_UI_DEFAULT {default_val}",
            f"#define {prefix}_{name}_AUDIO_MIN {c_float(float(p.get('audio_min', 0.0)))}",
            f"#define {prefix}_{name}_AUDIO_MAX {c_float(float(p.get('audio_max', 1.0)))}",
            f"#define {prefix}_{name}_DEFAULT_NORM {c_float(default_norm)}",
        ])
    lines.extend(["", f"#endif /* {prefix}_PARAMS_H */", ""])
    Path(out_path).write_text("\n".join(lines))
