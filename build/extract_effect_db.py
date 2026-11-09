"""Build the patch-editor effect database from .ZDL binaries.

Parses every ZDL's SonicStomp descriptor table (0x30-byte entries: OnOff,
effect-name self-entry, then one entry per knob with name/max/default) plus
the header's gid/fxid, and computes the 32-bit patch effect ID used inside
MS-series patch dumps:

    patchID = ((fxid & 0x3F) << 17) | (((fxid >> 6) & 1) << 30)
            | (((fxid >> 7) & 7) << 8) | (gid << 1)

Verified against all 137 stock MS-70CDR ZDLs vs g200kg/zoom-ms-utility's
effect list (137/137 match).

Usage:
    python3 build/extract_effect_db.py            # writes tools/effects_db.json
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))


from selector_metadata import attach_selectors

GID_CATEGORY = {
    1: "Dynamics", 2: "Filter", 3: "Drive", 4: "Amp", 5: "Pedal",
    6: "Modulation", 7: "SFX", 8: "Delay", 9: "Reverb",
}


def patch_id(fxid: int, gid: int) -> int:
    return (((fxid & 0x3F) << 17) | (((fxid >> 6) & 1) << 30)
            | (((fxid >> 7) & 7) << 8) | (gid << 1))


def _walk_descriptor(data: bytes, off: int):
    """Walk 0x30-byte descriptor entries from `off` until the sentinel."""
    entries = []
    while True:
        e = data[off:off + 0x30]
        if len(e) < 0x30:
            return None
        raw = e[:10].split(b"\0")[0]
        # 0x1F is a glyph in the pedal's font: Graphic EQ names its bands
        # "160\x1f" ... "12k\x1f", i.e. "160Hz" ... "12kHz". Rejecting it
        # dropped every GEQ from the DB, so PE showed it as an unknown id (#5).
        if any((c < 0x20 and c != 0x1F) or c > 0x7E for c in raw):
            return None                     # non-printable name: not a table
        nm = raw.replace(b"\x1f", b"Hz").decode("ascii")
        maxv, = struct.unpack_from("<I", e, 0x0C)
        defv, = struct.unpack_from("<I", e, 0x10)
        flags, = struct.unpack_from("<I", e, 0x2C)
        entries.append((nm, maxv, defv, flags))
        off += 0x30
        if flags & 0x04:                    # last-entry sentinel
            return entries
        if len(entries) > 12:
            return None


def parse_zdl(path: Path):
    """The descriptor table always begins with an 'OnOff' entry — find it by
    content (works for both our SonicStomp symbol and stock ZDLs, which name
    the table after the effect, plus files whose ELF headers parse oddly)."""
    data = path.read_bytes()
    gid = data[0x3C]
    fxid = data[0x40] | (data[0x41] << 8)

    entries = None
    i = 0
    while True:
        i = data.find(b"OnOff\x00", i)
        if i < 0:
            break
        entries = _walk_descriptor(data, i)
        if entries and len(entries) >= 2 and entries[1][1] == 0xFFFFFFFF:
            break                           # entry 1 = effect self-entry
        entries = None
        i += 1

    if not entries:
        print(f"  skip (no descriptor table): {path.name}")
        return None
    eff_name = entries[1][0]
    # Declared DSP cost: float at self-entry (descriptor entry 1) +0x28. The
    # firmware sums these per patch; "DSP Full" above ~230. PE's DSP meter.
    cost = struct.unpack_from('<f', data, i + 0x30 + 0x28)[0]
    params = [
        {"name": nm, "max": maxv, "default": defv}
        for nm, maxv, defv, _fl in entries[2:]
        if nm and maxv != 0xFFFFFFFF
    ]
    from parameter_display import restore_names
    restore_names(eff_name, params)
    return attach_selectors({
        "name": eff_name,
        "fxid": fxid,
        "gid": gid,
        "category": GID_CATEGORY.get(gid, f"gid{gid}"),
        "id": patch_id(fxid, gid),
        "params": params,
        "cost": round(cost, 2) if 0 < cost < 1000 else None,
    })


def _cover_b64(path: Path):
    """Row-major MSB-first 1024-byte cover bitmap, base64 (None if undecodable)."""
    import base64
    try:
        from decode_picture import decode_picture
        px, _ = decode_picture(str(path))
        b = bytearray()
        for y in range(64):
            for xb in range(16):
                byte = 0
                for bit in range(8):
                    if px[y][xb * 8 + bit]:
                        byte |= 1 << (7 - bit)
                b.append(byte)
        return base64.b64encode(bytes(b)).decode()
    except Exception:
        return None


def _rank(path: Path) -> int:
    n = path.name
    if path.parent.name == "dist":
        return 0
    for i, pre in enumerate(
            ("MS-70CDR_",), start=1):
        if n.startswith(pre):
            return i
    for i, pre in enumerate(("MS-50G_", "MS-60B_", "G1on_", "G1Xon_", "B1Xon_"), start=3):
        if n.startswith(pre):
            return i
    return 2                              # bare-name files (MS-70CDR era)


def check_dist_filenames() -> None:
    """dist/ is the folder Effect Manager installs from. The pedal cuts ZDL
    basenames to 8 characters, and two installed files with equal cut-down
    names freeze it on boot -- NAMLite-amptrec + NAMLite-smokey (both
    'NAMLite-') did exactly that on 2026-09-28. Refuse to build the DB over it."""
    seen = {}
    for f in sorted(x for x in (ROOT / "dist").iterdir() if x.suffix.lower() == ".zdl"):
        if len(f.stem) > 8:
            raise SystemExit(f"dist/{f.name}: basename longer than 8 characters "
                             "(the pedal truncates it; see docs/SAFE-DSP-RULES.md)")
        key = f.stem.lower()
        if key in seen:
            raise SystemExit(f"dist/{f.name} and dist/{seen[key]} collide on the pedal")
        seen[key] = f.name
        from zdl_size_guard import check as size_check     # larger files froze the pedal
        size_check(f)


# Effects in dist/ made by others, shown under their maker in the Patch Editor.
# Matujuice ZDL effects pack v1.5, MIT (dist/matujuice/LICENSE), unmodified
# release files: github.com/matujuice/zoom-ms-zdl-effects-pack
MATUJUICE = "Matujuice pack v1.5 by Luca Matturro (MIT)"
CREDITS = {name: MATUJUICE for name in ("Breather", "Choral", "DirtBox", "DualShft", "DubSiren", "EuGate",
                                       "GridDly", "SGNL", "Scrub", "Sweep", "SyncEQ", "WaveFold")}


def _private(paths):
    """dist/ files git ignores: NAM captures, cab fits, third-party IR banks."""
    import subprocess
    r = subprocess.run(["git", "check-ignore", "--stdin"], cwd=ROOT, text=True,
                       input="\n".join(str(p.relative_to(ROOT)) for p in paths), capture_output=True)
    return {ROOT / line for line in r.stdout.split()}


def main() -> None:
    # --public: the DB that gets committed. Leaves out everything git ignores in
    # dist/ and the local capture/cab names, so no private capture leaks into the
    # repo. Without it, the DB (and PE) also show what is staged locally.
    public = "--public" in sys.argv
    check_dist_filenames()
    best = {}                             # patch id -> (rank, entry, is_custom)
    # Probes build to build/probes/, not dist/, so they stay out of the release
    # set -- but the editor still needs to know their knobs, otherwise a probe
    # loaded on the pedal shows up as "unknown effect 0x..." with generic p1..p9
    # names and you cannot drive the experiment from PE. Scanned into their own
    # group so they never mix with the shipped pack.
    # Case-insensitive: third-party tools write lowercase .zdl (IRMesa.zdl).
    files = (sorted(x for x in (ROOT / "dist").iterdir() if x.suffix.lower() == ".zdl")
             + sorted((ROOT / "build" / "probes").rglob("*.ZDL"))
             + sorted((ROOT / "stock_zdls").glob("*.ZDL")))
    if public:
        hidden = _private([f for f in files if f.parent == ROOT / "dist"])
        files = [f for f in files if f not in hidden]
    probe_paths = set((ROOT / "build" / "probes").rglob("*.ZDL"))
    for f in files:
        e = parse_zdl(f)
        if not e:
            continue
        r = _rank(f)
        cur = best.get(e["id"])
        if cur is None or r < cur[0]:
            e["cover"] = _cover_b64(f)
            if f.parent == ROOT / "dist" and f.stem in CREDITS:
                e["credit"] = CREDITS[f.stem]
            best[e["id"]] = (r, e, r == 0, f in probe_paths)

    db = {"custom": [], "stock": [], "probes": []}
    for r, e, is_custom, is_probe in sorted(best.values(), key=lambda x: x[1]["name"].upper()):
        if is_probe:
            db["probes"].append(e)
        else:
            db["custom" if is_custom else "stock"].append(e)

    # Zoom's stock effects are local only (docs/STOCK-FILES.md). Without them,
    # keep the stock entries the current effect list already has: dropping them
    # would make the Patch Editor show every stock effect as unknown.
    if not any((ROOT / "stock_zdls").glob("*.ZDL")):
        current = ROOT / "tools" / "effects_db.json"
        db["stock"] = json.loads(current.read_text())["stock"] if current.exists() else []
        print(f"stock_zdls/ is not here (docs/STOCK-FILES.md): kept the {len(db['stock'])} stock "
              "entries from tools/effects_db.json")

    # Reserved self-service NAM identities; templates contain no capture data.
    nam_slots = json.loads((ROOT / 'tools' / 'nam_template' / 'multi.json').read_text())['slots']
    for meta in nam_slots:
        slot = meta['slot']
        template = ROOT / 'tools' / 'nam_template' / meta['file']
        if template.exists():
            e = parse_zdl(template)
            assert e and e['fxid'] == meta['fxid']
            # A build staged in dist/ for this slot knows its real knobs; the
            # template only has the loader's three. NAMEQ (slot 6) adds
            # Bass/Mid/Treb, and without this PE showed it as a 3-knob effect.
            # Same trust the local-name step already gives dist/ files.
            staged = next((x for x in db['custom'] if x['id'] == e['id']), None)
            for group in db.values():
                group[:] = [x for x in group if x['id'] != e['id']]
            if staged and staged.get('params') and len(staged['params']) > len(e.get('params', [])):
                e['params'] = staged['params']
            if staged and staged.get('cost'):
                e['cost'] = staged['cost']     # e.g. an Eco build staged in dist/ declares less
            # A staged file's own picture (its name and icon), else the template's.
            e.update(name=f'NAMLite — capture {slot}', namSlot=slot,
                     cover=(staged or {}).get('cover') or _cover_b64(template))
            db['custom'].append(e)

    # Reserved CabIR slots: one cab per effect (FXID 930..), built by the
    # loader page from tools/cab_template; templates hold a flat "no cab".
    for template in sorted((ROOT / 'tools' / 'cab_template').glob('slot-*.bin')):
        e = parse_zdl(template)
        slot = e['fxid'] - 929
        assert e and 1 <= slot <= 99
        staged = next((x for x in db['custom'] if x['id'] == e['id']), None)
        for group in db.values():
            group[:] = [x for x in group if x['id'] != e['id']]
        if staged and staged.get('cost'):
            e['cost'] = staged['cost']         # the dist/ file's declared cost (e.g. COSTnnn probes)
        e.update(name=f'CabIR — slot {slot}', cabSlot=slot,
                 cover=(staged or {}).get('cover') or _cover_b64(template))
        db['custom'].append(e)

    # Slots 17..216 (NAM FXID 500-699, CabIR 700-899) are made in the browser
    # from one base template each; PE expands them from this rule instead of
    # 400 near-identical entries. A file staged in dist/ for one of them
    # becomes that slot's entry (its own knobs, cost and embedded name).
    gens = {}
    for kind, key, tpl, man_name, label in (('nam', 'namSlot', 'nam_template', 'multi.json', 'NAMLite — capture {}'),
                                            ('cab', 'cabSlot', 'cab_template', 'cab.json', 'CabIR — slot {}')):
        g = json.loads((ROOT / 'tools' / tpl / man_name).read_text()).get('generated')
        if not g:
            continue
        gens[kind] = dict(first=g['first'], last=g['last'], fxidOffset=g['fxid_offset'], key=key, proto=1,
                          label=label.replace('{}', '%d'))
        for e in db['custom']:
            slot = e['fxid'] - g['fxid_offset']
            if e['gid'] == 8 and g['first'] <= slot <= g['last'] and not e.get(key):
                e.update(name=label.format(slot), **{key: slot})
    if gens:
        db['generated'] = gens

    from nam_capture_names import apply_local_names, apply_local_cab_names
    if not public:
        apply_local_names(db['custom'], ROOT)
        apply_local_cab_names(db['custom'], ROOT)

    # ---- legacy fxid aliases -------------------------------------------------
    # Every fxid an effect has EVER shipped under. Old patches (and pedals still
    # running an old build) reference these ids; without aliases the editor
    # shows "unknown effect 0x…" for effects that are installed and playing
    # fine. Alias entries reuse the current build's params/cover.
    LEGACY_FXIDS = {
        "Microlm":  [474],
        "Flower":   [475],
        "Shatter":  [476],
        "Arrakis":  [453],
        "Corrupt":  [477],
        "Klang":    [478],
        "Scorch":   [479],
        "Howl":     [480],
        "Taffy":    [460, 482],
        "Dissolve": [481],
        "Mangle":   [462, 463, 464, 465, 467, 468, 469, 483],
        "Rooms":    [471],
        "Spool":    [409],
    }
    current_ids = {e["id"] for e in db["custom"]} | {e["id"] for e in db["stock"]}
    db["legacy"] = []
    for e in db["custom"]:
        for old in LEGACY_FXIDS.get(e["name"], []):
            if old == e["fxid"]:
                continue
            lid = patch_id(old, e["gid"])
            if lid in current_ids:
                continue
            alias = dict(e)
            alias["fxid"] = old
            alias["id"] = lid
            alias["legacy"] = True
            alias["name"] = f"{e['name']} (old {old})"
            db["legacy"].append(alias)
    # Same idea for effects that changed CATEGORY (gid) but kept their fxid.
    # NAMLite first shipped in Filter (its entry point is still Fx_FLT_NAMLite)
    # before moving to Delay, so patches from then reference the Filter id.
    # This alias used to be hand-added to effects_db.json, and every regeneration
    # -- including each build_all.py run -- silently dropped it. Generate it.
    LEGACY_GIDS = {
        "NAMLite": [2],
    }
    # Probes too: NAMLite (FXID 498) was archived out of dist/ on 2026-09-28 and
    # now only exists under build/probes/, but old patches still reference it.
    for e in db["custom"] + db["probes"]:
        for old_gid in LEGACY_GIDS.get(e["name"], []):
            if old_gid == e["gid"]:
                continue
            lid = patch_id(e["fxid"], old_gid)
            if lid in current_ids:
                continue
            alias = dict(e)
            alias["gid"] = old_gid
            alias["category"] = GID_CATEGORY.get(old_gid, f"gid{old_gid}")
            alias["id"] = lid
            alias["legacy"] = True
            alias["name"] = f"{e['name']} (old {alias['category']})"
            db["legacy"].append(alias)
    db["legacy"].sort(key=lambda x: x["name"].upper())
    print(f"legacy aliases: {len(db['legacy'])}")

    # sanity: no patch-ID collisions
    ids = {}
    for kind in ("custom", "stock"):
        for e in db[kind]:
            if e["id"] in ids:
                print(f"WARNING: patch-ID collision {e['name']} vs {ids[e['id']]}")
            ids[e["id"]] = e["name"]

    # sanity: no effect-ID collision with a stock effect. The pedal identifies
    # an effect by gid and fxid together: Zoom's own files reuse fxids across
    # groups (DELAY, COMP, LINESEL, TREMOLO and HDHALL are all fxid 8), and
    # Skull (8/416) runs beside SPC_HOLE (9/416) on an MS-70CDR 2.10.
    stock_fx = {}
    for e in db["stock"]:
        if "fxid" in e:
            stock_fx.setdefault((e["gid"], e["fxid"]), e["name"])
    for e in db["custom"]:
        if (e.get("gid"), e.get("fxid")) in stock_fx:
            print(f"*** effect-ID COLLISION: custom {e['name']} {e['gid']}/{e['fxid']} == stock "
                  f"{stock_fx[(e['gid'], e['fxid'])]} — PICK A DIFFERENT fxid, this breaks on hardware ***")

    db_json = json.dumps(db, indent=1)

    out = ROOT / "tools" / "effects_db.json"
    out.write_text(db_json)
    print(f"{len(db['custom'])} custom + {len(db['stock'])} stock + {len(db['probes'])} probes -> {out}")

    # The patch editor embeds the DB INLINE (const DB={...};) so it works over
    # file:// without a fetch. Keep that inline copy in sync — otherwise the
    # editor silently runs a stale DB and shows freshly-built effects as
    # "unknown effect 0x…". Splice the same JSON into the HTML.
    import re
    editor = ROOT / "tools" / "patch_editor.html"
    if editor.exists():
        html = editor.read_text()
        # Find the inline object by PARSING it, not by regex. The old pattern
        # `const DB=\{[\s\S]*?\n\};` assumed the object ended with "};" on its own
        # line, which held while it was written with indent=1. Once the inline
        # copy became one compact line, the non-greedy match ran on to the next
        # "\n};" deep in the script and replaced everything between -- deleting
        # syncNamCaptureNames() and the BYID lookup table, and breaking 12 of 19
        # editor tests. raw_decode returns the exact end of the JSON value
        # whatever its formatting, so the splice can only ever touch the object.
        n = 0
        start = html.find("const DB=")
        if start >= 0:
            obj_at = start + len("const DB=")
            try:
                _, obj_end = json.JSONDecoder().raw_decode(html, obj_at)
            except ValueError:
                obj_end = -1
            if obj_end > 0 and html[obj_end:obj_end + 1] == ";":
                # Compact, matching the editor's one-line form: an indent=1 copy
                # inlines ~10k extra lines into the page for no benefit.
                inline = json.dumps(db, separators=(",", ":"))
                new_html = html[:obj_at] + inline + html[obj_end:]
                n = 1
        if n == 1:
            # Also stamp the effect list into the startup log. A stale cached page
            # is indistinguishable from a missing effect otherwise -- you only find
            # out by hunting the dropdown for something that IS in the file.
            names = ", ".join(e["name"] for e in db["custom"])
            new_html = re.sub(
                r'log\(`effect DB: [^;]*;(?:\n *log\("custom: [^\n]*\);)?',
                'log(`effect DB: ${DB.custom.length} custom + ${DB.stock.length} stock '
                '(incl. other MS/G1/B1 pedals)`);\n'
                f'log("custom: {names}");',
                new_html, count=1)
            editor.write_text(new_html)
            print(f"synced inline DB -> {editor}")
        else:
            print(f"WARNING: could not find inline 'const DB={{...}};' block in {editor}")


if __name__ == "__main__":
    main()
