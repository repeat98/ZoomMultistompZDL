# Hand-drawn cover overrides

Drop a `<EffectName>.json` here (exported from [`tools/cover_editor.html`](../../../../tools/cover_editor.html))
to replace an effect's generated cover with a hand-drawn 128×64 bitmap.

`custom_covers.make_cover()` checks this directory first: if `<Name>.json`
exists, that exact bitmap is used and the procedural cover (name + emblem +
knob row) is skipped. Otherwise the cover is generated as usual.

The name must match the effect's `effect_name` (e.g. `Reel.json`, `Galactic.json`).

## Workflow
1. Open `tools/cover_editor.html` in a browser.
2. **Load cover → pick the effect → Load** (or import a PNG / start blank).
3. Edit. Use the **device-aspect preview** (right) — drag the *pixel aspect*
   slider until a drawn circle looks round on your actual pedal, then draw with
   the ellipse tool's "round on device" box checked.
4. **Download cover JSON** and save it here as `<Name>.json`.
5. Rebuild that effect (`python3 src/.../<effect>/build.py`) and re-flash.
