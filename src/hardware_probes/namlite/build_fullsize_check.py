#!/usr/bin/env python3
"""Keep neural 0.02's entire layout; replace only its audio entry with NAMTest's
hardware-verified context shuttle and return. No neural instruction can execute.
"""
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'build'))
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl
from zdl import Zdl

NEURAL_HASH = 'b9d7fe4e762ea00934190ddf7c3d91c24cef9942d69b91a29e8fbb826b6db159'
# TI-compiled stage-1 NAMTest shuttle, then return via B3; all addresses are
# obtained from ctx, with no relocations, stack, buffers, or embedded pointers.
SHUTTLE = bytes.fromhex(
    '66821102646291010060000063838c0065028c01e602100276020c0200000000')


def main():
    source = ROOT/'build/probes/namlite/neural-0.02/NAMLite.ZDL'
    data = source.read_bytes()
    assert hashlib.sha256(data).hexdigest() == NEURAL_HASH, 'Unexpected neural baseline'
    assert len(data) == 47166
    # Compare against the actually hardware-tested NAMTest artifact.
    smoke = Zdl.load(ROOT/'build/probes/namtest/NAMTest.ZDL').elf
    smoke_text = _read_elf_sections(smoke)['.text']
    assert smoke[smoke_text['offset']:smoke_text['offset']+32] == SHUTTLE
    elf = Zdl.load(source).elf
    sec = _read_elf_sections(elf)
    text, const = sec['.text'], sec['.const']
    cd = elf[const['offset']:const['offset']+const['size']]
    desc = cd.index(b'OnOff\0')
    audio_va = struct.unpack_from('<I', cd, desc+0x30+0x20)[0]
    assert audio_va == text['addr'] == 0
    start = data.index(b'\x7fELF') + text['offset']
    result = bytearray(data)
    result[68:72] = b'0.04'
    result[start:start+32] = SHUTTLE
    assert len(result) == len(data)
    assert all(a == b or i in range(68,72) or i in range(start,start+32)
               for i,(a,b) in enumerate(zip(data,result)))
    out = ROOT/'build/probes/namlite/fullsize-check'
    out.mkdir(parents=True, exist_ok=True)
    target = out/'NAMLite.ZDL'
    target.write_bytes(result)
    assert parse_zdl(target) == parse_zdl(source), 'Effect identity or parameter metadata changed'
    report = dict(version='0.04', bytes=len(result),
        sha256=hashlib.sha256(result).hexdigest(), neural_baseline_sha256=NEURAL_HASH,
        same_layout=True, unchanged_except='version and first 32 audio bytes',
        audio='hardware-tested NAMTest context shuttle and return',
        neural_execution=False, hardware_result='pending')
    (out/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
