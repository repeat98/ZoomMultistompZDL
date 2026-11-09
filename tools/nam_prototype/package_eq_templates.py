#!/usr/bin/env python3
"""Package the NAM Loader's eight capture templates (engine 0.25).

0.25 = 0.24 + 51-row tone table (3 KB smaller, even knobs exact) + flat-EQ
skip (Bass/Mid/Treb all 50: ~130 cycles). --steps 7 builds the Eco set: the
network runs 7 of 8 samples (~650 cycles less; the lost 4-8 kHz is under a
cab's roll-off) into --out, for a capture used in front of CabIR.
0.24 = 0.23 + predicate-free steady-state input/output loops (NAM_FAST_IO):
~650 fewer emulated cycles; output within rounding (~90 dB) of 0.23.
0.23 = 0.22 + noise gate (knob 7, nam_gate.h); Gate 0 is bit-identical to 0.22.
0.22 = 0.21 + register-accumulated tap loops (exact_rings regacc): 15,763 vs
20,011 emulated cycles per callback, output bit-identical to 0.21.

Engine 0.21 is the NAMFull2/NAMEQ kernel that plays at full rate on the pedal:
exactly sized, interleaved history rings (bit-identical output to the original
power-of-two kernel, ~86 KB working set instead of 137 KB against a 128 KB L2)
plus the Bass/Mid/Treb tone stack voiced like the NAM plugin. It replaces the
0.14 templates (tested NAMLite 0.12 block DSP), which crackled at full rate;
those are archived in build/nam-archive/2026-09-28/nam_template-0.14/.

The loader contract (tools/nam_template/multi.json, format 2) is unchanged: each
slot is a complete ZDL with its 1,871 weights zeroed; the browser writes a
capture's weights at `weights_offset`, the 12-byte display name at
`name_offset`, and the version at 68, after checking the template's size and
SHA-256. Weight ORDER is unchanged -- exact_rings and the tone stack never touch
`nam_weights` -- so the loader's existing reorder() applies as-is.

Any compatible A2 Lite capture can seed the build: its weights are located in
the linked file byte-for-byte (taken from the compiled object's own
`nam_weights`, not re-derived from decimal, which could differ by an ulp),
required to occur exactly once, and zeroed. Nothing of the seed capture ships.

    python3 tools/nam_prototype/package_eq_templates.py <seed.nam>
"""
import hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/nam_prototype'), str(ROOT / 'build')]
from generate_block import generate_block
import exact_rings, tone_stack
from linker import LinkerConfig, ObjFile, link, params_from_manifest
from zdl import Zdl
from capture_art import picture as capture_picture
from gen_init_materialize import _read_elf_sections
from extract_effect_db import parse_zdl

VERSION = '0.26'
TONE_PARAMS = [dict(name='Bass', max=100, default=50), dict(name='Mid', max=100, default=50),
               dict(name='Treb', max=100, default=50), dict(name='Gate', max=100, default=0)]
N_WEIGHTS = 1871
SLOTS = 16
# Declared DSP cost (descriptor +0x28; the pedal says "DSP Full" above ~230).
# Calibrated on hardware: Eco 7/8 + CabIR (10) + Great Muff (30.43) ticked
# -> 7/8 > 189.6; NAM full + Great Muff ran (0.21/0.22, and 0.25 is ~4%
# lighter) -> full <= 199.5. Scaled by measured callback cost (full 15,148 /
# 7/8 14,658 / 6/8 13,841 emulated). Pedal limit measured with pass-through
# probes (2026-10-06): 194 + Great Muff (224.4) accepted, 198 + Muff (228.4)
# refused -> limit in (224.4, 228.4], not the ~230 reported elsewhere.
DSP_COST = {8: 194.0, 7: 188.0, 6: 181.0, 4: 152.0}   # 0.26: Eco 6/8 +331 cycles (cubic resampling); 4 = Eco+


def nam_fxid(slot):
    """Slots 1-8: 900-907; 9-16: 950-957 (908-913 were the retired CabIR bank and
    NAM test effects). Mirrors namFxid in tools/nam_loader.js."""
    return 899 + slot if slot <= 8 else 941 + slot


def nam_ident(slot):
    return f'NAMSlot{slot}' if slot <= 9 else f'NAMSl{slot}'     # effect names stay <= 8 chars


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('seed', type=Path)
    ap.add_argument('--steps', type=int, default=8, choices=[4, 6, 7, 8], help='4 = Eco+ (with --eco-eq)')
    ap.add_argument('--out', type=Path, default=ROOT / 'tools/nam_template')
    ap.add_argument('--eco-eq', action='store_true',
                    help='Eco+: three correction biquads after the network, fitted and written by the loader (NAM_ECO_EQ)')
    ap.add_argument('--split', action='store_true',
                    help='split (NAM_SPLIT): amp on one output, dry on the other (side written by the loader); knob 3 = Dry level')
    a = ap.parse_args()
    seed = a.seed.resolve()
    eco = a.steps < 8
    work = ROOT / (f'build/probes/namlite/template-{VERSION}' + ('-eco' if eco else '') + ('-eq' if a.eco_eq else '') + ('-split' if a.split else ''))
    generate_block(seed, work)
    exact_rings.apply(work, interleave=True, regacc=True, extra_counts=(a.steps,) if eco else ())
    tone_stack.write_table(work, half=True)

    ti = Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS')
    obj = work / 'namlite.obj'
    subprocess.run([str(ti / 'bin/cl6x'), '--c99', '-O2', '-mv6740', '--abi=eabi', '--mem_model:data=far',
                    '--fp_mode=strict', '--fp_reassoc=off', '-DNAM_TONE_STACK', '-DNAM_GATE', '-DNAM_FAST_IO',
                    *(['-DNAM_SPLIT'] if a.split else []),
                    *(['-DNAM_ECO_EQ'] if a.eco_eq else []),
                    *([f'-DNAM_RATE_STEPS={a.steps}'] if eco else []),
                    f'--include_path={ti}/include', f'--include_path={ROOT}/src/airwindows/common',
                    f'--include_path={ROOT}/src/hardware_probes/namlite',
                    f'--include_path={work}', '--keep_asm', f'--asm_directory={work}', '-c',
                    str(ROOT / 'src/hardware_probes/namlite/namlite.c'), f'--output_file={obj}'],
                   check=True, timeout=900)
    o = ObjFile(obj)
    assert not any(s['name'] and not s['shndx'] for s in o.symbols), 'unresolved helper symbol'
    for sec in o.sections:
        if sec['name'] in ('.text', '.bss', '.far', '.fardata') or sec['name'].startswith('.switch'):
            assert not sec['size'], f"unexpected section {sec['name']}"
    ws = next(s for s in o.symbols if s['name'] == 'nam_weights')
    weights = bytes(o.sections[ws['shndx']]['data'][ws['value']:ws['value'] + N_WEIGHTS * 4])
    assert len(weights) == N_WEIGHTS * 4

    m = json.loads((ROOT / 'src/hardware_probes/namlite/manifest.json').read_text())
    base = m['params']
    if a.split:      # knob 3 is the dry side's level in split files
        base = [dict(p, name='Dry', default=50) if p['name'] == 'Mix' else p for p in base]
    extra = []
    params = params_from_manifest(base + TONE_PARAMS + extra)
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    picture = capture_picture('NAM')
    slots, texts = [], set()
    for old in out.glob('slot-*.bin'):
        old.unlink()
    for i in range(1, SLOTS + 1):
        fxid = nam_fxid(i)
        p = out / f'slot-{i}.bin'
        link(LinkerConfig(effect_name=nam_ident(i), audio_func_name=m['audio_func_name'], gid=8, fxid=fxid,
                          params=params, obj_path=obj, output_path=p, fxid_version=VERSION.encode(),
                          screen_image=picture, materialize_init=True, use_object_edit_handlers=False,
                          synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                          knob3_blob_path=str(work / 'unused'), dsp_cost=DSP_COST[a.steps]))
        z = Zdl.load(p)
        s = _read_elf_sections(z.elf)
        cs = s['.const']
        base = 20 + z.header_size + cs['offset']
        data = bytearray(p.read_bytes())
        assert data.count(weights) == 1, f'slot {i}: seed weights not found exactly once'
        w_at = data.index(weights)
        name_at = z.elf[cs['offset']:cs['offset'] + cs['size']].index(b'OnOff\0') + base + 48
        assert data[name_at:name_at + len(nam_ident(i))] == nam_ident(i).encode(), f'slot {i}: name field not where expected'
        t = s['.text']
        texts.add(hashlib.sha256(z.elf[t['offset']:t['offset'] + t['size']]).hexdigest())
        data[w_at:w_at + N_WEIGHTS * 4] = bytes(N_WEIGHTS * 4)       # no capture ships
        p.write_bytes(data)
        from zdl_size_guard import check as size_check
        size_check(p)                                  # over-size templates froze the pedal
        entry = parse_zdl(p)
        assert entry['fxid'] == fxid and len(entry['params']) == 7 + len(extra)
        extra_at = {}
        if a.split:                                    # where the loader writes the routing
            import struct
            pattern = struct.pack('<4f', 1, 0, 0, 27182.818)
            assert data.count(pattern) == 1, f'slot {i}: split routing not found exactly once'
            extra_at['split_route_offset'] = data.index(pattern)
        if a.eco_eq:                                   # the correction table, found by its identity default + marker
            import struct
            pattern = struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 16180.339)
            assert data.count(pattern) == 1, f'slot {i}: Eco+ table not found exactly once'
            extra_at['eco_eq_offset'] = data.index(pattern)
        slots.append(dict(slot=i, fxid=fxid, id=entry['id'], file=p.name, bytes=len(data),
                          sha256=hashlib.sha256(data).hexdigest(), weights_offset=w_at, name_offset=name_at, **extra_at))
    # Same object linked eight times: the audio code must be the same bytes in
    # every slot (addresses are PC-relative or relocated, so they do not differ).
    assert len(texts) == 1, f'.text differs between slots ({len(texts)} variants)'
    (out / 'multi.json').write_text(json.dumps(dict(
        format=2,
        engine=f'NAMLite engine {VERSION}' + (f' Eco{"+" if a.eco_eq else ""} {a.steps}/8' if eco else ': full rate') + (', split' if a.split else '') + ', exact interleaved rings, register-accumulated taps, fast I/O, Bass/Mid/Treb, Gate, soft limiter',
        weights_count=N_WEIGHTS, version_offset=68, output_version=VERSION, sample_rate=44100,
        dsp_cost=DSP_COST[a.steps], eco=eco, eco_steps=a.steps, eco_plus=bool(a.eco_eq), split=bool(a.split),
        model_rate=44100 * a.steps // 8,
        slots=slots), indent=2) + '\n')
    print(f'Packaged {SLOTS} capture templates (900-907, 950-957), engine {VERSION}{" Eco" if eco else ""} -> {out}, 7 knobs; .text identical in all slots.')


if __name__ == '__main__':
    main()
