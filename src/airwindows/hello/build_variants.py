#!/usr/bin/env python3
"""Build HELLO-derived hardware probes for the edit-mode knob-count bug."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))

from linker import LinkerConfig, Param, link  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    "--opt_for_space=3",
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]


@dataclass(frozen=True)
class Variant:
    name: str
    fxid: int
    params: list[Param]
    image_count: int
    header_words: tuple[int, int]
    positions: list[tuple[int, int, int]]
    notes: str
    audio_func_name: str | None = None
    disable_knob3_blob: bool = True
    emit_dummy_coe_relocs: bool = False


def compile_hello() -> Path:
    src_c = HERE / "hello.c"
    obj = HERE / "hello.obj"
    print(f"[variants] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )
    return obj


def build_variant(obj: Path, variant: Variant) -> None:
    out_zdl = ROOT / "dist" / f"{variant.name}.ZDL"
    out_zdl.parent.mkdir(exist_ok=True)

    cfg = LinkerConfig(
        effect_name=variant.name,
        gid=2,
        fxid=variant.fxid,
        params=variant.params,
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=b"1.01",
        flags_byte=0x01,
        audio_func_name=variant.audio_func_name,
        knob_positions=variant.positions,
        image_info_knob_count=variant.image_count,
        image_info_header_words=variant.header_words,
        emit_dummy_coe_relocs=variant.emit_dummy_coe_relocs,
        knob3_blob_path="/tmp/__nonexistent__" if variant.disable_knob3_blob else None,
    )
    print(f"\n[variants] {variant.name}: {variant.notes}")
    link(cfg)


def main() -> None:
    obj = compile_hello()

    variants = [
        Variant(
            name="H1ONE",
            fxid=0x01A1,
            params=[Param("AAA111", 100, 50)],
            image_count=1,
            header_words=(28, 17),
            positions=[(2, 54, 36)],
            notes="1 descriptor param, imageInfo count=1",
        ),
        Variant(
            name="H2TWO",
            fxid=0x01A2,
            params=[Param("AAA111", 100, 50), Param("BBB222", 100, 50)],
            image_count=2,
            header_words=(28, 17),
            positions=[(2, 40, 7), (3, 57, 7)],
            notes="2 descriptor params, stock two-knob imageInfo count=2",
        ),
        Variant(
            name="H3REAL",
            fxid=0x01A3,
            params=[
                Param("Knob 1", 100, 50),
                Param("Knob 2", 100, 50),
                Param("Knob 3", 100, 50),
            ],
            image_count=3,
            header_words=(32, 17),
            positions=[(2, 31, 13), (3, 54, 13), (4, 77, 13)],
            notes="3 params, Exciter imageInfo geometry, object-defined third edit handler",
            audio_func_name="Fx_FLT_HELLO",
            disable_knob3_blob=False,
        ),
        Variant(
            name="H3NOP",
            fxid=0x01A4,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
            ],
            image_count=3,
            header_words=(32, 17),
            positions=[(2, 31, 13), (3, 54, 13), (4, 77, 13)],
            notes="3 params with loud labels, third edit handler is unique NOP",
        ),
        Variant(
            name="H3COE",
            fxid=0x01A7,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
            ],
            image_count=3,
            header_words=(32, 17),
            positions=[(2, 31, 13), (3, 54, 13), (4, 77, 13)],
            notes="3 params plus stock-like leading Coe relocs in .rela.dyn",
            emit_dummy_coe_relocs=True,
        ),
        Variant(
            name="H3DLL",
            fxid=0x01A8,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
            ],
            image_count=3,
            header_words=(32, 17),
            positions=[(2, 31, 13), (3, 54, 13), (4, 77, 13)],
            notes="3 params with the fixed Dll descriptor-entry count",
        ),
        Variant(
            name="H3IMG2",
            fxid=0x01A5,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
            ],
            image_count=2,
            header_words=(28, 17),
            positions=[(2, 40, 7), (3, 57, 7)],
            notes="3 descriptor params but imageInfo count=2",
        ),
        Variant(
            name="H5FIVE",
            fxid=0x01A6,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
                Param("DDD444", 100, 50),
                Param("EEE555", 100, 50),
            ],
            image_count=5,
            header_words=(21, 23),
            positions=[(2, 21, 36), (3, 45, 36), (4, 69, 36)],
            notes="5 descriptor params, AIR-style paged imageInfo count=5",
        ),
        Variant(
            name="H5DLL",
            fxid=0x01A9,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
                Param("DDD444", 100, 50),
                Param("EEE555", 100, 50),
            ],
            image_count=5,
            header_words=(21, 23),
            positions=[(2, 21, 36), (3, 45, 36), (4, 69, 36)],
            notes="5 params with the fixed Dll descriptor-entry count",
        ),
        Variant(
            name="H7DLL",
            fxid=0x01AA,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
                Param("DDD444", 100, 50),
                Param("EEE555", 100, 50),
                Param("FFF666", 100, 50),
                Param("GGG777", 100, 50),
            ],
            image_count=7,
            header_words=(21, 23),
            positions=[(2, 21, 36), (3, 45, 36), (4, 69, 36)],
            notes="7 params; descriptor count matches stock GraphicEQ's 9 entries",
        ),
        Variant(
            name="H9DLL",
            fxid=0x01AB,
            params=[
                Param("AAA111", 100, 50),
                Param("BBB222", 100, 50),
                Param("CCC333", 100, 50),
                Param("DDD444", 100, 50),
                Param("EEE555", 100, 50),
                Param("FFF666", 100, 50),
                Param("GGG777", 100, 50),
                Param("HHH888", 100, 50),
                Param("III999", 100, 50),
            ],
            image_count=9,
            header_words=(21, 23),
            positions=[(2, 21, 36), (3, 45, 36), (4, 69, 36)],
            notes="9 params; full apparent firmware ceiling",
        ),
    ]

    for variant in variants:
        build_variant(obj, variant)

    print("\n[variants] done")
    for variant in variants:
        print(f"  dist/{variant.name}.ZDL  - {variant.notes}")


if __name__ == "__main__":
    main()
