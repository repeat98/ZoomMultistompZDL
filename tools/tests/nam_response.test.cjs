// tools/nam_response.js: FFT, transfer measurement and the A2 Lite forward pass.
const test = require('node:test');
const assert = require('node:assert');
const R = require('../nam_response.js');

test('FFT matches a direct DFT', () => {
  const n = 64, x = Array.from({length: n}, (_, i) => Math.sin(i * 0.7) + 0.3 * Math.cos(i * 2.1) + (i % 5) * 0.1);
  const re = Float64Array.from(x), im = new Float64Array(n);
  R.fft(re, im);
  for (let k = 0; k < n; k++) {
    let a = 0, b = 0;
    for (let t = 0; t < n; t++) { a += x[t] * Math.cos(-2 * Math.PI * k * t / n); b += x[t] * Math.sin(-2 * Math.PI * k * t / n); }
    assert.ok(Math.abs(re[k] - a) < 1e-9 && Math.abs(im[k] - b) < 1e-9, `bin ${k}`);
  }
});

test('transfer: unity, -6 dB and a delay read as flat', () => {
  const x = R.pink(1 << 15, 3), half = x.map(v => v * 0.5), late = Float64Array.from(x, (_, i) => (i >= 10 ? x[i - 10] : 0));
  const f = R.grid(), at = hz => f.findIndex(v => v >= hz);
  for (const [y, want] of [[x, 0], [half, -6.02], [late, 0]]) {
    const db = R.smooth(R.transfer(x, y), R.FS, f);
    for (const hz of [100, 1000, 10000]) assert.ok(Math.abs(db[at(hz)] - want) < 0.2, `${hz} Hz: ${db[at(hz)]} vs ${want}`);
  }
});

test('pink noise has RMS 1 and falls ~3 dB per octave', () => {
  const x = R.pink(1 << 16, 9);
  assert.ok(Math.abs(Math.sqrt(x.reduce((s, v) => s + v * v, 0) / x.length) - 1) < 1e-9);
  const re = Float64Array.from(x.subarray(0, 1 << 16)), im = new Float64Array(1 << 16);
  R.fft(re, im);
  const band = (lo, hi) => { let s = 0, n = 0; for (let k = lo; k < hi; k++) { s += re[k] * re[k] + im[k] * im[k]; n++; } return 10 * Math.log10(s / n); };
  const slope = band(1486, 2972) - band(743, 1486);             // ~1-2 kHz vs ~0.5-1 kHz
  assert.ok(slope < -2 && slope > -4, `slope ${slope}`);
});

test('forward: weight count, causality, and the head bias path', () => {
  const nw = 1871;
  assert.throws(() => R.forward(new Array(nw - 1).fill(0)));
  const w = new Array(nw).fill(0); w[nw - 2] = 0.25; w[nw - 1] = 2;   // head bias 0.25, head scale 2
  const step = R.forward(w);
  for (let i = 0; i < 50; i++) assert.strictEqual(step(Math.sin(i)), 0.5);
  let s = 7;
  const rnd = () => ((s = (s * 1103515245 + 12345) >>> 0) / 4294967296 - 0.5) * 0.2;
  const ws = Array.from({length: nw}, rnd), a = R.forward(ws), b = R.forward(ws);
  const x = Array.from({length: 600}, (_, i) => Math.sin(i * 0.05)), y = x.map(v => a(v));
  const x2 = x.slice(); x2[400] += 1;                            // a change at 400 must not move earlier outputs
  const y2 = x2.map(v => b(v));
  for (let i = 0; i < 400; i++) assert.strictEqual(y2[i], y[i]);
  assert.ok(y.every(Number.isFinite) && y2.slice(400).some((v, i) => v !== y[400 + i]));
});

test('ecoProcess at 8 of 8 is the network, with the resampler latency', () => {
  // The input is read one sample late and the output two steps late. The
  // network has biases, so its reference is fed the same leading zero sample.
  let s = 3;
  const rnd = () => ((s = (s * 1103515245 + 12345) >>> 0) / 4294967296 - 0.5) * 0.2;
  const w = Array.from({length: 1871}, rnd), step = R.forward(w);
  const x = Float64Array.from({length: 2048}, (_, i) => 0.3 * Math.sin(i * 0.03) + (i % 7) * 0.01);
  const ref = [0, ...x].map(v => step(v)), y = R.ecoProcess(w, x, 8);
  assert.strictEqual(y[0], 0); assert.strictEqual(y[1], 0);     // the output history starts at 0
  for (let i = 2; i < 2048; i++) assert.ok(Math.abs(y[i] - ref[i - 2]) < 1e-9, `sample ${i}`);
});

test('fitEcoEq returns three stable biquads and the curves it fitted', async () => {
  let s = 9;
  const rnd = () => ((s = (s * 1103515245 + 12345) >>> 0) / 4294967296 - 0.5) * 0.3;
  const w = Array.from({length: 1871}, rnd);
  const r = await R.fitEcoEq(w, {steps: 4});
  assert.strictEqual(r.coefficients.length, 15);
  for (let k = 0; k < 3; k++) {
    const a1 = r.coefficients[5 * k + 3], a2 = r.coefficients[5 * k + 4];
    assert.ok(Math.abs(a2) < 1 && Math.abs(a1) < 1 + a2, `biquad ${k} stable`);
  }
  assert.strictEqual(r.lossDb.length, 3);
  assert.strictEqual(r.correctionDb.length, r.freqs.length);
});
