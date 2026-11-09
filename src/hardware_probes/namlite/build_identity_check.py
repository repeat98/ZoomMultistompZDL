#!/usr/bin/env python3
"""0.07 diagnostic: replace only 0.06 weights and version, preserving DSP code."""
import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'build'), str(ROOT/'tools/nam_prototype')]
from linker import ObjFile
from zdl import Zdl
from gen_init_materialize import _read_elf_sections
from generate import load, K, D
from generate_compact import compact

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Build 0.09 delayed-identity test')
    args = parser.parse_args()
    version = '0.09' if args.history else '0.07'
    source = ROOT/'build/probes/namlite/compact-0.06'
    out = ROOT/'build/probes/namlite'/('history-check' if args.history else 'identity-check')
    out.mkdir(parents=True, exist_ok=True)
    data = (source/'NAMLite.ZDL').read_bytes()
    assert hashlib.sha256(data).hexdigest() == '400e743f5531ac2cb571a67eadc7d39125c74d5f0f9ddffa4198f78bf75571a0'
    _, template, *_ = load(source/'lite.nam')
    model = copy.deepcopy(template)
    # Carry x and -x unchanged through all residual layers. Each contributes
    # LReLU(x), LReLU(-x); their difference is 1.01*x for either sign.
    weights = [1., -1., 0.]
    for k in K:
        conv = np.zeros((3,3,k), np.float32)
        conv[0,0,-1] = conv[1,1,-1] = 1
        weights.extend(conv.ravel().tolist())
        weights.extend([0.] * 18)  # bias, condition, residual matrix/bias
    head = np.zeros((3,16), np.float32)
    head[0,-1] = 1/(23*1.01)
    head[1,-1] = -1/(23*1.01)
    weights.extend(head.ravel().tolist())
    weights.extend([0., 1.])
    if args.history:
        # z0=LReLU(delayed-current), z1=LReLU(current-delayed).
        # (z0-z1)/1.01 reconstructs delayed-current for both signs.
        # The residual adds this to current, cascading every layer's delay.
        # Summed heads telescope to delayed-input; channel 2 adds input back.
        weights = [1., 0., 0.]
        for layer, k in enumerate(K):
            conv = np.zeros((3,3,k), np.float32)
            conv[0,0,0] = 1; conv[0,0,-1] = -1
            conv[1,0,0] = -1; conv[1,0,-1] = 1
            bias = [0., 0., 2. if layer == 22 else 0.]
            condition = [0., 0., 1. if layer == 22 else 0.]
            residual = np.zeros((3,3), np.float32)
            residual[0,0] = 1/1.01; residual[0,1] = -1/1.01
            weights.extend(conv.ravel().tolist()); weights.extend(bias)
            weights.extend(condition); weights.extend(residual.ravel().tolist())
            weights.extend([0.]*3)
        head = np.zeros((3,16), np.float32)
        head[:,0] = [1/1.01, -1/1.01, 1.]
        weights.extend(head.ravel().tolist()); weights.extend([-2., 1.])
    assert len(weights) == 1871
    model['weights'] = weights
    model['sample_rate'] = 48000
    model['metadata'] = {'name': 'NAMLite history diagnostic' if args.history else 'NAMLite identity diagnostic (not a capture)'}
    model_path = out/('history.nam' if args.history else 'identity.nam')
    model_path.write_text(json.dumps(model, indent=2)+'\n')
    compact(model_path, out)
    # Patch a known hardware-loading binary so zero-valued diagnostic weights
    # cannot cause the compiler to optimize away any neural instructions.
    obj = ObjFile(source/'namlite.obj')
    old = bytes(obj.get_section('.const:nam_weights')['data'])
    elf = Zdl.load(source/'NAMLite.ZDL').elf
    const = _read_elf_sections(elf)['.const']
    cd = elf[const['offset']:const['offset']+const['size']]
    assert cd.count(old) == 1
    start = data.index(b'\x7fELF') + const['offset'] + cd.index(old)
    _, _, pre, layers, head, bias, scale = load(model_path)
    table = list(pre)
    for cw, b, mix, rw, rb in layers:
        table.extend(cw.transpose(2,0,1).ravel())
        table.extend(b); table.extend(mix); table.extend(rw.ravel()); table.extend(rb)
    table.extend(head.ravel()); table.extend([bias, scale])
    replacement = np.asarray(table, dtype='<f4').tobytes()
    assert len(replacement) == len(old)
    result = bytearray(data)
    result[68:72] = version.encode('ascii')
    result[start:start+len(old)] = replacement
    assert all(a == b or 68 <= i < 72 or start <= i < start+len(old)
               for i,(a,b) in enumerate(zip(data, result)))
    (out/'NAMLite.ZDL').write_bytes(result)
    report = {'version':version, 'purpose':'delayed unity neural diagnostic' if args.history else 'unity neural diagnostic, not fuzz',
              'bytes':len(result), 'sha256':hashlib.sha256(result).hexdigest(),
              'audio_code_and_layout':'byte-identical to 0.06',
              'changes':'weight table and version only', 'hardware':'pending',
              'limitation':'Does not establish capture fidelity or worst-case DSP timing.' if args.history else 'Does not validate nonzero dilated history taps or capture fidelity.'}
    if args.history:
        report['delay_samples'] = sum((k-1)*d for k,d in zip(K,D))+15
        report['delay_ms_at_44100'] = report['delay_samples']*1000/44100
        report['startup'] = 'First 15 raw kernel samples are -2; existing 8192-sample muted warmup hides this.'
    (out/'binary-validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
