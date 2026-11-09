#!/usr/bin/env python3
"""Read-only validation of every release init and its rebased handler calls."""
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from build_all import RELEASE_PLUGINS
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl
from linker import _init_materialize_body, _INIT_MAT_PROLOGUE, _INIT_MAT_STRIDE, _INIT_MAT_BRANCH_OFF
from zdl import Zdl


def verify():
    rows = []
    expected_names = set()
    for name, build in RELEASE_PLUGINS:
        mf = build.parent / 'manifest_pedal.json'
        if not mf.exists():
            mf = build.parent / 'manifest.json'
        manifest = json.loads(mf.read_text())
        path = ROOT / 'dist' / (manifest['effect_name'] + '.ZDL')
        expected_names.add(path.name)
        blob = Zdl.load(path).elf
        sections = _read_elf_sections(blob)
        text, const = sections['.text'], sections['.const']
        cd = blob[const['offset']:const['offset'] + const['size']]
        desc = cd.index(b'OnOff\0')
        count = len(manifest['params'])
        word = lambda off: struct.unpack_from('<I', cd, off)[0]
        init_va = word(desc + 0x30 + 0x1c)
        targets = [word(desc + (i + 2)*0x30 + 0x1c) for i in range(count)]
        expected = _init_materialize_body(targets, init_va)
        start = text['offset'] + init_va - text['addr']
        assert text['addr'] <= init_va < text['addr'] + text['size'], path
        assert blob[start:start + len(expected)] == expected, f'{path}: init differs'
        for i, target in enumerate(targets):
            assert text['addr'] <= target < text['addr'] + text['size'], path
            assert blob[text['offset'] + target - text['addr']:][:2] == bytes.fromhex('f731'), f'{path}: handler prologue'
            off = len(_INIT_MAT_PROLOGUE) + i*_INIT_MAT_STRIDE + _INIT_MAT_BRANCH_OFF
            ins = struct.unpack_from('<I', blob, start + off)[0]
            delta = (ins >> 7) & 0x1fffff
            if delta & 0x100000:
                delta -= 0x200000
            for base in [0, 0x10000000, 0x11820000]:
                assert ((base + init_va + off) & ~31) + 4*delta == base + target
        parsed = parse_zdl(path)
        assert [{k:p[k] for k in ('name','max','default')} for p in parsed['params']] == [{k:p[k] for k in ('name','max','default')} for p in manifest['params']], path
        assert parsed['fxid'] == manifest['fxid'] and parsed['gid'] == manifest['gid'], path
        rows.append(dict(name=manifest['effect_name'], params=count, init=hex(init_va),
                         sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert {p.name for p in (ROOT/'dist').glob('*.ZDL')} == expected_names
    db = json.loads((ROOT/'tools/effects_db.json').read_text())
    html = (ROOT/'tools/patch_editor.html').read_text()
    embedded = re.search(r"const DB=(\{[\s\S]*?\n\});", html)
    assert embedded and json.loads(embedded.group(1)) == db, 'inline editor DB differs'
    for row in rows:
        parsed = parse_zdl(ROOT/'dist'/(row['name']+'.ZDL'))
        entry = next(e for e in db['custom'] if e['id']==parsed['id'])
        assert all(entry[k]==v for k,v in parsed.items()), row['name']
    return rows


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
