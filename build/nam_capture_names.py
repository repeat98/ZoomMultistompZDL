"""Known local capture names; browser export records take precedence in PE."""
import re

SHORT = r'[A-Za-z0-9][A-Za-z0-9_-]{0,7}'


def _gen_slot(root, tpl, man, fxid):
    """Slot of an FXID in a manifest's generated range (17..216), else None."""
    import json
    g = json.loads((root / 'tools' / tpl / man).read_text()).get('generated')
    slot = fxid - g['fxid_offset'] if g else 0
    return slot if g and g['first'] <= slot <= g['last'] else None


def _nam_slot_of(root, fxid):
    """Capture slot of a NAM FXID (1-8: 900-907, 9-16: 950-957, 17-216: 500-699),
    from the loader's manifest."""
    import json
    slots = json.loads((root / 'tools' / 'nam_template' / 'multi.json').read_text())['slots']
    return next((s['slot'] for s in slots if s['fxid'] == fxid), None) or _gen_slot(root, 'nam_template', 'multi.json', fxid)


def _embedded_name(path):
    """The 12-byte display-name field (OnOff entry + 48), as the packager finds it."""
    data = path.read_bytes()
    at = data.find(b'OnOff\0')
    if at < 0:
        return ''
    return data[at + 48:at + 60].split(b'\0')[0].decode('ascii', 'replace')


def local_capture_names(root):
    """slot -> short name for NAM captures staged in dist/.

    Two sources, in order of trust:
      1. The full 12-byte display name embedded in the ZDL, `NAM-<short>`
         (read directly: parse_zdl reads only 10 characters).
      2. A legacy filename, `NAMLite-<short>.ZDL`. The loader no longer writes
         these: every `NAMLite-` name truncates to the same 8 characters, and
         two installed files with equal truncated names froze the pedal on
         boot (hardware, 2026-09-29). It now writes `NAM<slot><4 chars>.ZDL`,
         which is too short to carry the name -- hence the embedded name first.
    """
    from extract_effect_db import parse_zdl
    by_file, by_embed = {}, {}
    for path in sorted((root / 'dist').glob('*.ZDL')):
        effect = parse_zdl(path)
        slot = _nam_slot_of(root, effect['fxid']) if effect and effect['gid'] == 8 else None
        if not slot:
            continue
        if path.stem.startswith('NAMLite-'):
            short = path.stem[len('NAMLite-'):]
            if re.fullmatch(SHORT, short):
                by_file.setdefault(slot, set()).add(short)
        name = _embedded_name(path) or effect.get('name') or ''
        if name.startswith('NAM-') and re.fullmatch(SHORT, name[4:]):
            by_embed.setdefault(slot, set()).add(name[4:])
    # Two different names for one identity cannot tell us which is installed.
    out = {}
    for slot in set(by_file) | set(by_embed):
        names = by_embed.get(slot) or by_file.get(slot)
        if len(names) == 1:
            out[slot] = next(iter(names))
    return out

def apply_local_names(entries, root):
    names = local_capture_names(root)
    for effect in entries:
        if effect.get('namSlot'):
            short = names.get(effect['namSlot'])
            effect.pop('captureName', None)
            if short:
                effect['captureName'] = short
                effect['name'] = 'NAMLite-' + short


def apply_local_cab_names(entries, root):
    """CabIR slots staged in dist/ (FXID 930..): name them from the embedded
    'CAB-<name>' display name, as PE does for NAM captures."""
    from extract_effect_db import parse_zdl
    names = {}
    for path in sorted((root / 'dist').iterdir()):
        if path.suffix.lower() != '.zdl':
            continue
        effect = parse_zdl(path)
        if not (effect and effect['gid'] == 8):
            continue
        slot = effect['fxid'] - 929 if 930 <= effect['fxid'] <= 945 else _gen_slot(root, 'cab_template', 'cab.json', effect['fxid'])
        if not slot:
            continue
        label = _embedded_name(path)
        short = label[4:] if label.startswith('CAB-') else label     # e.g. the COSTnnn probes
        if re.fullmatch(SHORT, short):
            names[slot] = short
    for effect in entries:
        slot = effect.get('cabSlot')
        if slot and slot in names:
            effect['captureName'] = names[slot]
            effect['name'] = 'CabIR-' + names[slot]
