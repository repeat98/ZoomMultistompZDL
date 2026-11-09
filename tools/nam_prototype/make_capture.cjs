// Build a capture ZDL with the NAM Loader's own code path (convertNamed), as
// the browser does -- used to stage dist/ captures and to check that the
// loader's output equals a direct build.
//   node tools/nam_prototype/make_capture.cjs <capture.nam> <out.ZDL> <slot 1-216> <short name>
// TPL=<dir> uses another template set (e.g. an archived one) instead of tools/nam_template.
// ICON=<id> picks the cover icon (tools/cover_art.js; default: the manifest's).
const fs = require('node:fs'), path = require('node:path');
const root = path.resolve(__dirname, '../..');
const [namPath, outPath, slotArg, shortName] = process.argv.slice(2);
const slotNo = Number(slotArg), tpl = process.env.TPL || path.join(root, 'tools/nam_template');
const api = require(path.join(root, 'tools/nam_loader.js')), ids = require(path.join(root, 'tools/slot_identity.js'));
(async () => {
  const manifest = JSON.parse(fs.readFileSync(path.join(tpl, 'multi.json')));
  const slot = ids.slotMeta(manifest, slotNo);       // slots past 16: the shared base template
  const template = fs.readFileSync(path.join(tpl, slot.file));
  const r = await api.convertNamed(JSON.parse(fs.readFileSync(namPath)), template, manifest, slotNo, shortName, process.env.ICON);
  fs.writeFileSync(outPath, Buffer.from(r.bytes));
  console.log(JSON.stringify({file: r.report.filename, display: r.report.displayName, fxid: r.report.fxid,
    version: r.report.version, bytes: r.bytes.length}));
})().catch(e => { console.error('LOADER ERROR:', e.message); process.exit(1); });
