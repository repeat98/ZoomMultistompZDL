#!/usr/bin/env python3
"""Experimental full-rate A2 Lite layout with exact-capacity history rings.

No model/rate/equation changes. Requires NAM_RESET_RINGS(&st->net) when the
wrapper initializes a new instance. Outputs private generated data under build;
does not modify the converter or publish a pedal build.
"""
import argparse
import json
from pathlib import Path
from generate_block import generate_block
from generate import K, D


def generate_exact(model, out):
    out = Path(out)
    generate_block(model, out)
    header = (out / 'nam_kernel_pedal.h').read_text()
    old_sizes = [1 << (((k - 1) * d + 8) - 1).bit_length() for k, d in zip(K, D)]
    sizes = [(k - 1) * d + 8 for k, d in zip(K, D)]
    old_history = 3 * sum(n + 2 for n in old_sizes) + 3 * 34
    history = 3 * sum(n + 2 for n in sizes) + 3 * 34
    replacements = {
        'unsigned pos,pad;': 'unsigned pos,pad,ring_pos[24];',
        f'history[{old_history}]': f'history[{history}]',
        'static const unsigned nam_sizes[] = {' + ','.join(map(str, old_sizes)) + '};':
            'static const unsigned nam_sizes[] = {' + ','.join(map(str, sizes)) + '};',
        'unsigned stride=n+2;': 'unsigned stride=n+2,lp=s->ring_pos[layer];',
        'p=(pos+i)&(n-1);': 'p=lp+i; if(p>=n)p-=n;',
        'q=(pos+i-(k-1-t)*d)&(n-1);':
            'int qi=(int)(lp+i)-(int)((k-1-t)*d);\n'
            '                if(qi<0)qi+=(int)n; else if(qi>=(int)n)qi-=(int)n;\n'
            '                q=(unsigned)qi;',
        'w=b+18;off+=3*stride;':
            'lp+=count; if(lp>=n)lp-=n; s->ring_pos[layer]=lp;\n'
            '        w=b+18;off+=3*stride;',
    }
    for old, new in replacements.items():
        assert header.count(old) == 1, old
        header = header.replace(old, new)
    header += '\n#define NAM_RESET_RINGS(s) do { unsigned nr; for(nr=0;nr<24;nr++) (s)->ring_pos[nr]=0; } while(0)\n'
    (out / 'nam_kernel_pedal.h').write_text(header)
    host = (out / 'nam_kernel.c').read_text()
    suffix = host[host.index('unsigned nam_state_bytes'):]
    suffix = suffix.replace('s->pos=0;', 's->pos=0;NAM_RESET_RINGS(s);')
    suffix = suffix.replace(f'i<{old_history}', f'i<{history}')
    (out / 'nam_kernel.c').write_text(header + suffix)
    report = json.loads((out / 'geometry.json').read_text())
    report.update(state_bytes=8+96+4*(114+history), history_floats=history,
                  representation='exact-capacity planar rings, per-layer cursors',
                  history_and_weights_bytes=history*4+1871*4,
                  wrapper_initialization='must invoke NAM_RESET_RINGS on new state')
    (out / 'geometry.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('model',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();generate_exact(a.model,a.out)
