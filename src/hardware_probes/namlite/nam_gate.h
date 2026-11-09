/* Noise gate for NAMLite (knob 7, "Gate"). 0 = off; 1..100 = threshold
 * -99.3 .. -30 dB (-100 + 0.7 * knob), measured on the raw mono input.
 *
 * Detection is on the INPUT, gain reduction is applied to the model's OUTPUT
 * (after the tone stack), like the NAM plugin's gate: a high-gain capture
 * turns the tiny hiss of pickups and cable into audible amp noise, and the
 * gate mutes that between notes without changing anything while you play.
 *
 * Per 8-sample callback, all scalar, outside every loop: block mean square ->
 * envelope (fast rise, ~10 ms fall) -> open above the threshold, stay open
 * down to 6 dB below it (hysteresis) plus a 30 ms hold -> gain ramps to 1 in
 * ~0.5 ms or to 0 over ~50 ms. The gain is interpolated across the block into
 * net.gain[], which the output loop already multiplies in, so no pipelined loop
 * gains a predicate. Knob 0 keeps the gain at exactly 1.0: bit-identical to
 * the engine without the gate.
 *
 * Table = threshold as mean-square power, 10^((-100 + 0.7k)/10); row 0 unused.
 * Regenerate: python3 -c "print([10**((-100+0.7*k)/10) for k in range(1,101)])" */
#ifndef NAM_GATE_H
#define NAM_GATE_H
#define NAM_GATE_HOLD   165u       /* callbacks: 165 * 8 / 44100 = 30 ms */
#define NAM_GATE_OPEN   0.35f      /* gain step toward 1 per callback: ~0.5 ms */
#define NAM_GATE_CLOSE  0.0036f    /* toward 0 per callback: ~50 ms */
#define NAM_GATE_RISE   0.5f       /* envelope, per callback */
#define NAM_GATE_FALL   0.018f     /* ~10 ms */
static const float nam_gate_thr[101] = {
    0.0f, 1.17489755e-10f, 1.38038426e-10f, 1.6218101e-10f, 1.90546072e-10f,
    2.23872114e-10f, 2.63026799e-10f, 3.09029543e-10f, 3.63078055e-10f, 4.26579519e-10f,
    5.01187234e-10f, 5.88843655e-10f, 6.91830971e-10f, 8.12830516e-10f, 9.54992586e-10f,
    1.12201845e-09f, 1.31825674e-09f, 1.54881662e-09f, 1.81970086e-09f, 2.13796209e-09f,
    2.51188643e-09f, 2.95120923e-09f, 3.4673685e-09f, 4.07380278e-09f, 4.78630092e-09f,
    5.62341325e-09f, 6.60693448e-09f, 7.76247117e-09f, 9.12010839e-09f, 1.07151931e-08f,
    1.25892541e-08f, 1.47910839e-08f, 1.73780083e-08f, 2.04173794e-08f, 2.39883292e-08f,
    2.81838293e-08f, 3.31131121e-08f, 3.89045145e-08f, 4.5708819e-08f, 5.37031796e-08f,
    6.30957344e-08f, 7.41310241e-08f, 8.7096359e-08f, 1.02329299e-07f, 1.20226443e-07f,
    1.41253754e-07f, 1.65958691e-07f, 1.9498446e-07f, 2.29086765e-07f, 2.6915348e-07f,
    3.16227766e-07f, 3.71535229e-07f, 4.36515832e-07f, 5.12861384e-07f, 6.02559586e-07f,
    7.07945784e-07f, 8.31763771e-07f, 9.77237221e-07f, 1.14815362e-06f, 1.34896288e-06f,
    1.58489319e-06f, 1.86208714e-06f, 2.18776162e-06f, 2.57039578e-06f, 3.01995172e-06f,
    3.54813389e-06f, 4.16869383e-06f, 4.89778819e-06f, 5.75439937e-06f, 6.76082975e-06f,
    7.94328235e-06f, 9.33254301e-06f, 1.0964782e-05f, 1.28824955e-05f, 1.51356125e-05f,
    1.77827941e-05f, 2.08929613e-05f, 2.45470892e-05f, 2.8840315e-05f, 3.38844156e-05f,
    3.98107171e-05f, 4.67735141e-05f, 5.49540874e-05f, 6.45654229e-05f, 7.58577575e-05f,
    8.91250938e-05f, 0.000104712855f, 0.000123026877f, 0.000144543977f, 0.000169824365f,
    0.000199526231f, 0.000234422882f, 0.00027542287f, 0.000323593657f, 0.000380189396f,
    0.000446683592f, 0.00052480746f, 0.000616595002f, 0.00072443596f, 0.000851138038f,
    0.001f
};
#endif
