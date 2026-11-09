#!/usr/bin/env python3
"""Slot templates for the NAM + Cab Loader: slots 1-16, and the base for 17..216.

Two jobs, for each engine (NAM full, NAM Eco 6/8, CabIR):

1. Named covers. Every template reserves capture_art.PICTURE_CAPACITY bytes for
   the cover so the loader can draw the user's name into it (tools/
   cover_art.js) without moving anything else in the file. Slots 1-16 are
   relinked with that reserved picture from the same compiled object. The
   data after the picture moves, so the linker rewrites the addresses in the
   code; the code size is checked here and the sound in the emulator
   (host_vs_emulator / namcheck: bit-identical output).

2. Generated slots 17..216. Linked slots differ only in the FXID in the ZDL
   header, the slot digits in the effect's name (which also names its exported
   symbols), and the ELF .hash table those names hash into, so one base
   template per engine covers them all: tools/slot_identity.js writes the FXID
   and digits and rebuilds .hash exactly as build/linker.py does. The manifest
   records linker-built reference slots (SHA-256); the tests regenerate them
   from the base and must match byte for byte.

Before any of that, slot 1 is relinked with the original cover and must equal
the shipped slot-1 template, which proves the compiled object is the engine
already on pedals. Run once; rerunning on its own output is refused (the
shipped slot-1 check then fails), so restore the manifests to rebuild.

Identities (permanent once released -- patches store the FXID):
  NAM  1-8: 900-907, 9-16: 950-957, 17-216: 500-699 ('NAMS' + 3 digits)
  Cab  1-16: 930-945,               17-216: 700-899 ('CabS' + 3 digits)

    python3 tools/nam_prototype/package_generated_slots.py [nam] [eco] [ecoplus] [split] [cab]
"""
import base64, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools/nam_prototype'), str(ROOT / 'build'), str(ROOT / 'src/hardware_probes/cab_ir'),
                str(ROOT / 'src/airwindows/common')]
from linker import LinkerConfig, ObjFile, link, params_from_manifest
from screen_image import Canvas
import capture_art as A
from zdl_size_guard import check as size_check
from extract_effect_db import parse_zdl
import package_eq_templates as P

FIRST, LAST = 17, 216
REFERENCE = [17, 18, 99, 100, 150, 216]
WORK = ROOT / 'build/probes/generated-slots'


def nam_fxid(slot):
    return P.nam_fxid(slot) if slot <= 16 else 483 + slot


def cab_fxid(slot):
    return 929 + slot if slot <= 16 else 683 + slot


def sha(b):
    return hashlib.sha256(b).hexdigest()


def text_size(data):
    """Size of the audio code. Its bytes change with the bigger picture -- the
    code holds the addresses of the data tables after it, which the linker
    rewrites -- so equivalence is checked by running it (emulator), not here."""
    from zdl import Zdl
    from gen_init_materialize import _read_elf_sections
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.ZDL') as f:
        f.write(data); f.flush()
        z = Zdl.load(Path(f.name))
        return _read_elf_sections(z.elf)['.text']['size']


def nam_engine(label, steps, eco_eq=False, split=False):
    obj = ROOT / ('build/probes/namlite/template-' + P.VERSION + ('-eco' if steps < 8 else '') + ('-eq' if eco_eq else '')
                  + ('-split' if split else '')) / 'namlite.obj'
    o = ObjFile(obj)
    ws = next(s for s in o.symbols if s['name'] == 'nam_weights')
    weights = bytes(o.sections[ws['shndx']]['data'][ws['value']:ws['value'] + P.N_WEIGHTS * 4])
    m = json.loads((ROOT / 'src/hardware_probes/namlite/manifest.json').read_text())
    base = [dict(p, name='Dry', default=50) if split and p['name'] == 'Mix' else p for p in m['params']]
    params = params_from_manifest(base + P.TONE_PARAMS)

    def build(slot, ident, picture):
        out = WORK / label / f'slot-{slot}.out'          # not .ZDL: build/probes is scanned for probes
        out.parent.mkdir(parents=True, exist_ok=True)
        link(LinkerConfig(effect_name=ident, audio_func_name=m['audio_func_name'], gid=8, fxid=nam_fxid(slot),
                          params=params, obj_path=obj, output_path=out, fxid_version=P.VERSION.encode(),
                          screen_image=picture, materialize_init=True, use_object_edit_handlers=False,
                          synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                          knob3_blob_path=str(WORK / 'unused'), dsp_cost=P.DSP_COST[steps]))
        data = bytearray(out.read_bytes())
        assert data.count(weights) == 1, f'{label} slot {slot}: seed weights not found once'
        at = data.index(weights)
        data[at:at + len(weights)] = bytes(len(weights))      # no capture ships
        extra = dict(weights_offset=at)
        if split:                                             # split: where the loader writes the routing
            import struct
            mark = struct.pack('<4f', 1, 0, 0, 27182.818)
            assert data.count(mark) == 1, f'{label} slot {slot}: split routing not found once'
            extra['split_route_offset'] = data.index(mark)
        if eco_eq:                                            # Eco+: where the loader writes the correction
            import struct
            mark = struct.pack('<16f', 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 16180.339)
            assert data.count(mark) == 1, f'{label} slot {slot}: Eco+ table not found once'
            extra['eco_eq_offset'] = data.index(mark)
        return bytes(data), extra
    return build


def cab_engine():
    import build as C                               # src/hardware_probes/cab_ir/build.py
    obj = C.OUT / 'template/cab.obj'                # compiled with the marker coefficients
    params = params_from_manifest(C.PARAMS)
    mk = C.markers()

    def build(slot, ident, picture):
        out = WORK / 'cab' / f'slot-{slot}.out'
        out.parent.mkdir(parents=True, exist_ok=True)
        link(LinkerConfig(effect_name=ident, audio_func_name='Fx_REV_CabIR', gid=8, fxid=cab_fxid(slot),
                          params=params, obj_path=obj, output_path=out, fxid_version=C.VERSION.encode(),
                          screen_image=picture, materialize_init=True, use_object_edit_handlers=False,
                          synthesize_linesel_edit_handlers=True, synth_edit_start_index=2,
                          knob3_blob_path=str(WORK / 'unused'), dsp_cost=C.DSP_COST))
        data = out.read_bytes()
        offs = {}
        for key, block in (('fir', C.f32(mk['fir'])), ('sos', C.f32(mk['sos'])), ('gain', C.f32([mk['gain']]))):
            assert data.count(block) == 1, f'cab slot {slot}: {key} markers not found once'
            offs[key + '_offset'] = data.index(block)
        return C.fill_cab(data, offs, C.FLAT), offs
    return build


def _bits(c):
    """Row-major 1-bpp, MSB first: 16 bytes per row, 1024 in all."""
    out = bytearray(1024)
    for y in range(64):
        for x in range(128):
            if c.pixels[y][x]:
                out[y * 16 + x // 8] |= 0x80 >> (x % 8)
    return bytes(out)


def em_thumbnail(c):
    """RGBA bytes of the Effect Manager icon, as build/make_em_thumbnails.render."""
    from PIL import Image
    from lcd_geometry import PIXEL_ASPECT
    cover = Image.new('RGBA', (128, 64))
    cover.putdata([(0, 0, 0, 255) if bit else (255, 255, 255, 0) for row in c.pixels for bit in row])
    height = min(96, round(128 * 64 / 128 * PIXEL_ASPECT))
    cover = cover.resize((128, height), Image.Resampling.NEAREST)
    icon = Image.new('RGBA', (128, 96), (255, 255, 255, 0))
    icon.paste(cover, (0, (96 - height) // 2))
    return icon.tobytes()


def cover_block(kind):
    """What the loader needs to draw a cover: the bare panel, each icon as a mask
    of the pixels it turns white, and the name font. `check` holds hashes of
    covers drawn here, which the JS must reproduce."""
    from capture_icons import ICONS, DEFAULT_ICON, draw_icon
    bare = A.named_base(kind)
    icons = []
    for iid, label, _ in ICONS:
        c = A.named_base(kind)
        draw_icon(c, iid)
        mask = bytes(a ^ b for a, b in zip(_bits(c), _bits(bare)))
        icons.append(dict(id=iid, label=label, mask=base64.b64encode(mask).decode()))
    cases = [('smokey', None), ('sm57', 'cabinet'), ('tonehunt', 'skull'), ('a', 'heart'), ('Z-9_x', 'headphones'),
             ('', None)]
    return dict(kind=kind, capacity=A.PICTURE_CAPACITY, width=128, height=64, name_box=list(A.NAME_BOX),
                base=base64.b64encode(_bits(bare)).decode(), icons=icons, default_icon=DEFAULT_ICON[kind],
                font=A.NAME_FONT, name_scale_max=[5, 4],
                check=[dict(name=n, icon=i or DEFAULT_ICON[kind], picture=sha(A.named_picture(kind, n, i)),
                            thumbnail=sha(em_thumbnail(A.named_canvas(kind, n, i)))) for n, i in cases])


def package(label, tpl_dir, manifest_name, build, old_ident, prefix, fxid_of, kind, slot_file):
    mpath = tpl_dir / manifest_name
    man = json.loads(mpath.read_text())
    shipped = {s['slot']: s for s in man['slots']}
    assert 'cover' not in man, f'{label}: already packaged with named covers (restore the manifest to rebuild)'
    old, _ = build(1, old_ident(1), A.picture(kind))
    assert sha(old) == shipped[1]['sha256'], f'{label}: relinked slot 1 differs from the shipped template -- wrong object?'
    audio = text_size(old)
    blank = A.named_picture(kind, '')

    def finish(slot, ident, data, extra):
        assert data.count(blank) == 1, f'{label} slot {slot}: reserved picture not found once'
        name_at = data.index(ident.encode())                # first occurrence is the display-name field
        entry = dict(slot=slot, fxid=fxid_of(slot), **extra, name_offset=name_at, picture_offset=data.index(blank))
        assert text_size(data) == audio, f'{label} slot {slot}: audio code size changed'
        return entry

    slots = []
    for s in range(1, 17):
        ident = old_ident(s)
        data, extra = build(s, ident, blank)
        entry = finish(s, ident, data, extra)
        if 'id' in shipped[s]:
            entry['id'] = shipped[s]['id']
        f = tpl_dir / slot_file(s)
        f.write_bytes(data)
        size_check(f)
        entry.update(file=f.name, bytes=len(data), sha256=sha(data))
        assert parse_zdl(f)['fxid'] == entry['fxid']
        slots.append(entry)
    ident = f'{prefix}{FIRST:03d}'
    base, extra = build(FIRST, ident, blank)
    entry = finish(FIRST, ident, base, extra)
    (tpl_dir / 'gen-base.bin').write_bytes(base)
    size_check(tpl_dir / 'gen-base.bin')
    digits = [i + len(prefix) for i in range(len(base)) if base.startswith(ident.encode(), i)]
    assert len(digits) >= 3 and digits[0] == entry['name_offset'] + len(prefix)
    refs = {}
    for s in REFERENCE:
        b, e2 = build(s, f'{prefix}{s:03d}', blank)
        assert len(b) == len(base) and e2 == extra
        refs[str(s)] = sha(b)
    gen = dict(first=FIRST, last=LAST, fxid_offset=fxid_of(FIRST) - FIRST, file='gen-base.bin', bytes=len(base),
               sha256=sha(base), ident_prefix=prefix, ident_digits=3, ident_offsets=digits, reference_sha256=refs,
               **{k: v for k, v in entry.items() if k.endswith('_offset')})
    man.update(slots=slots, generated=gen, cover=cover_block(kind))
    mpath.write_text(json.dumps(man, indent=2) + '\n')
    print(f'{label}: 16 slots relinked, base {len(base)} B, picture at {entry["picture_offset"]} '
          f'({A.PICTURE_CAPACITY} B reserved), slots {FIRST}-{LAST} (FXID {fxid_of(FIRST)}-{fxid_of(LAST)})')


def main():
    # Which engines: all by default, or some by name (0.26 left the cabs alone).
    which = set(sys.argv[1:]) or {'nam', 'eco', 'ecoplus', 'split', 'cab'}
    if 'nam' in which:
        package('NAM full', ROOT / 'tools/nam_template', 'multi.json', nam_engine('nam', 8), P.nam_ident, 'NAMS',
                nam_fxid, 'NAM', lambda s: f'slot-{s}.bin')
    if 'eco' in which:
        package('NAM eco', ROOT / 'tools/nam_template_eco', 'multi.json', nam_engine('nam-eco', 6), P.nam_ident, 'NAMS',
                nam_fxid, 'NAM', lambda s: f'slot-{s}.bin')
    if 'ecoplus' in which:
        package('NAM eco+', ROOT / 'tools/nam_template_ecoplus', 'multi.json', nam_engine('nam-ecoplus', 4, eco_eq=True),
                P.nam_ident, 'NAMS', nam_fxid, 'NAM', lambda s: f'slot-{s}.bin')
    if 'split' in which:
        package('NAM split', ROOT / 'tools/nam_template_split', 'multi.json', nam_engine('nam-split', 8, split=True),
                P.nam_ident, 'NAMS', nam_fxid, 'NAM', lambda s: f'slot-{s}.bin')
    if 'cab' in which:
        package('CabIR', ROOT / 'tools/cab_template', 'cab.json', cab_engine(), lambda s: f'CabSl{s:02d}', 'CabS',
                cab_fxid, 'IR', lambda s: f'slot-{s:02d}.bin')


if __name__ == '__main__':
    main()
