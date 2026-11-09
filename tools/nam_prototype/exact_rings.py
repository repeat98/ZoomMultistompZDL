#!/usr/bin/env python3
"""Rewrite a generate_block kernel to use exactly sized history rings.

WHY. NAMProf measured the full-rate kernel on hardware at 32,333 cycles in its
fastest callback against 18,612 emulated -- 42% of the time stalled on memory,
50% on average. The cause is size: every layer's history ring is rounded up to
a power of two so the index can wrap with `& (n-1)`, which makes history
129.8 KB and the working set (with weights) 137 KB, just over the 128 KB L2
cache. Rings sized exactly -- (k-1)*d + 8 floats -- fit well inside L2.
Worst offenders: dilation 101 needs 513 and got 1,024; 239 needs 1,203, got 2,048.

WHAT CHANGES. Only indexing and layout. The maths, the coefficients and the order
of every accumulation are untouched: output is bit-identical (the host test
requires max difference 0).

NO PER-ITERATION CONDITIONS IN ANY LOOP -- this is the load-bearing design rule.
The first version wrapped each index with `if (q >= n) q -= n` inside the sample
loops. It was bit-exact on the host, but its TI build diverged in the emulator
(output grew until the wrapper's range check reset it, every ~14 callbacks),
and building with -mu (no software pipelining) made it correct again. So the
fault is in the software-pipelined form of loops whose wrap predicate changes
every iteration -- TI's pipeliner or the emulator's SPLOOP model, and we cannot
tell which from here. A TI miscompile could write outside a ring and freeze the
pedal, so that shape is avoided entirely. This version keeps every loop body
free of data-dependent predicates, like the power-of-two code that already runs
on hardware:

  - Each ring plane has an 8-float MIRROR after it: h[n..n+7] == h[0..7]. A tap
    reads 8 consecutive samples starting anywhere in [0, n), so its reads may run
    up to 7 past the end -- into the mirror -- and need no wrap at all. The one
    wrap per tap, `st0 = base + n - back; if (st0 >= n) st0 -= n`, is a scalar
    outside the sample loop.
  - Writes are split into at most two loops with bounds computed beforehand
    (`first = min(n - base, count)`), so neither loop wraps. The mirror is then
    refreshed with a fixed 8-iteration copy, before any tap reads it.
  - Contiguous reads with no masking is also what the SIMD/layout work wants.

Other details:
  - Each layer keeps its own position in [0, n) (`lpos`), because `& (n-1)` only
    worked on the free-running `pos` since powers of two divide 2^32.
  - n = (k-1)*d + 8 is exactly enough: the block writes its 8 frames before any
    tap reads, and the oldest tap is (k-1)*d back.
  - A per-layer range guard resets an out-of-range position to 0 -- corrupted
    state can then at worst give a wrong sample, never an out-of-bounds write.
  - Plane stride = n + 8 rounded up to even, and lpos has 24 slots, so every
    plane and the arrays after lpos stay 8-byte aligned as before.
  - NAM_EXACT_RINGS makes namlite.c zero lpos and bump its state version.

The final 16-tap head ring is already an exact 32 and is left alone.
"""
import re
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import K, D

N_LAYERS = len(K)
LPOS_SLOTS = 24                      # 23 used; even count keeps later arrays 8-aligned
MIRROR = 8
NEED = [(k - 1) * d + 8 for k, d in zip(K, D)]


def stride_of(n):
    return (n + MIRROR + 1) & ~1


def stride_interleaved(n):
    return (3 * (n + MIRROR) + 1) & ~1


def history_floats_exact(interleave=False):
    if interleave:
        return sum(stride_interleaved(n) for n in NEED) + 3 * 34
    return 3 * sum(stride_of(n) for n in NEED) + 3 * 34


def history_floats_pow2(sizes):
    return 3 * sum(n + 2 for n in sizes) + 3 * 34


def _once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f'exact_rings: expected exactly one "{what}", found {n}')
    return text.replace(old, new)


WRITE_OLD = '''        for(i=0;i<count;i++) {
            p=(pos+i)&(n-1);
            h[p]=v[i];h[stride+p]=v[10+i];h[2*stride+p]=v[20+i];
            zbuf[i]=b[0];zbuf[10+i]=b[1];zbuf[20+i]=b[2];
        }
'''
WRITE_NEW = '''        {   /* write without wrapping: at most two runs, bounds fixed beforehand */
            unsigned first=n-base;if(first>count)first=count;
            for(i=0;i<first;i++){p=base+i;h[p]=v[i];h[stride+p]=v[10+i];h[2*stride+p]=v[20+i];}
            for(i=first;i<count;i++){p=base+i-n;h[p]=v[i];h[stride+p]=v[10+i];h[2*stride+p]=v[20+i];}
            /* Refresh the mirror (h[n..n+7] == h[0..7]) only when this block
             * wrote into slots 0..7: base < 8, or the write wrapped. For the big
             * rings that is ~16 blocks in n. The test is a scalar OUTSIDE the
             * loop, so no loop body gains a data-dependent predicate. */
            if(base<8u||base+count>n)
                for(i=0;i<8;i++){h[n+i]=h[i];h[stride+n+i]=h[stride+i];h[2*stride+n+i]=h[2*stride+i];}
        }
        for(i=0;i<count;i++){zbuf[i]=b[0];zbuf[10+i]=b[1];zbuf[20+i]=b[2];}
'''

WRITE_NEW_IL = '''        {   /* write without wrapping: at most two runs, bounds fixed beforehand */
            unsigned first=n-base;if(first>count)first=count;
            for(i=0;i<first;i++){p=3u*(base+i);h[p]=v[i];h[p+1]=v[10+i];h[p+2]=v[20+i];}
            for(i=first;i<count;i++){p=3u*(base+i-n);h[p]=v[i];h[p+1]=v[10+i];h[p+2]=v[20+i];}
            /* mirror (24 floats = slots 0..7 x 3 channels), only when slots 0..7 were written */
            if(base<8u||base+count>n)
                for(i=0;i<24;i++)h[3u*n+i]=h[i];
        }
        for(i=0;i<count;i++){zbuf[i]=b[0];zbuf[10+i]=b[1];zbuf[20+i]=b[2];}
'''


TAP_OLD_IL = '''        for(i=0;i<count;i++){zbuf[i]=b[0];zbuf[10+i]=b[1];zbuf[20+i]=b[2];}
        /* Each coefficient set is reused across the whole block. Ring capacity
         * includes the extra seven future frames written above. */
        for(t=0;t<k;t++) {
            float w0=w[0],w1=w[1],w2=w[2],w3=w[3],w4=w[4];
            float w5=w[5],w6=w[6],w7=w[7],w8=w[8];
            unsigned st0=base+n-(k-1-t)*d;if(st0>=n)st0-=n;   /* one wrap per tap */
            for(i=0;i<count;i++) {
                q=3u*(st0+i);             /* interleaved; may run into the mirror */
                float a=h[q],c=h[q+1],e=h[q+2];
                float z0=zbuf[i],z1=zbuf[10+i],z2=zbuf[20+i];
                z0+=w0*a;z0+=w1*c;z0+=w2*e;
                z1+=w3*a;z1+=w4*c;z1+=w5*e;
                z2+=w6*a;z2+=w7*c;z2+=w8*e;
                zbuf[i]=z0;zbuf[10+i]=z1;zbuf[20+i]=z2;
            }
            w+=9;
        }
'''


def _regacc_block(group=4, extra_counts=(), extra_group=None):
    """8-sample tap loop with register accumulators, `group` samples per pass.

    Why groups. The old 8-iteration inner loop ran 6 stages deep, so ~40% of
    each run was pipeline fill and drain -- 156 times per callback -- and it
    round-tripped the partial sums through zbuf in memory on every tap.

    First attempt: all 8 samples in one pass, 24 accumulators. The compiler
    reported "Register pressure too high" at every ii from 37 to 51, found no
    schedule, spilled, and the callback went from 20,011 to 43,637 emulated
    cycles -- and its TI output was not bit-identical (0.19). So: two passes of
    4 samples, 12 accumulators each, which leaves room for weights and loads.
    Each pass re-reads the tap's 9 weights; that is cheap next to the MACs.

    Per accumulator the sums are the same terms in the same order as the
    original loop, so the output is bit-identical. The per-tap ring wrap is
    branch-free: this loop body is straight-line, so the compiler pipelines the
    TAP loop itself, and an if() there would be a per-iteration predicate in a
    pipelined loop -- the shape that failed twice. (x>>31) is all-ones iff x<0.
    """
    def groups(count, group=group):
        out = []
        for g0 in range(0, count, group):
            ss = range(g0, min(g0 + group, count))
            out.append(f'            {{   /* samples {g0}..{ss[-1]} */')
            out.append('                const float *wt=w;')
            out.append('                float ' + ','.join(f'Z{c}{s}=b[{c}]' for c in range(3) for s in ss) + ';')
            out += ['                for(t=0;t<k;t++) {',
                    '                    float w0=wt[0],w1=wt[1],w2=wt[2],w3=wt[3],w4=wt[4];',
                    '                    float w5=wt[5],w6=wt[6],w7=wt[7],w8=wt[8];',
                    '                    int x=(int)base-(int)((k-1-t)*d);',
                    '                    unsigned st0=(unsigned)(x+((int)n&(x>>31)));',
                    '                    const float * restrict hp=h+3u*st0;  /* may run into the mirror */']
            for s in ss:
                out.append(f'                    {{ float a=hp[{3*s}],c=hp[{3*s+1}],e=hp[{3*s+2}];')
                out.append(f'                      Z0{s}+=w0*a;Z0{s}+=w1*c;Z0{s}+=w2*e;'
                           f'Z1{s}+=w3*a;Z1{s}+=w4*c;Z1{s}+=w5*e;'
                           f'Z2{s}+=w6*a;Z2{s}+=w7*c;Z2{s}+=w8*e; }}')
            out += ['                    wt+=9;', '                }']
            out.append('                ' + ''.join(f'zbuf[{s}]=Z0{s};zbuf[{10+s}]=Z1{s};zbuf[{20+s}]=Z2{s};' for s in ss))
            out.append('            }')
        return out + ['            w+=9u*k;']

    # count==7: the 7/8-rate build (NAM_RATE_STEPS=7) runs the network on 7
    # samples per callback; without its own fast path it fell back to the slow
    # zbuf loop and was slower than full rate.
    L = ['        if(count==8u) {'] + groups(8)
    for c in extra_counts:
        L += [f'        }} else if(count=={c}u) {{'] + groups(c, extra_group or group)
    L.append('        } else {')
    body = TAP_OLD_IL.rstrip('\n').split('\n')
    L += ['    ' + x for x in body]
    L.append('        }')
    return '\n'.join(L) + '\n'


def transform(h: str, interleave: bool = False, regacc: bool = False, extra_counts=(), extra_group=None) -> str:
    """Return the exact-ring version of a generate_block pedal header.

    interleave=True stores the three channels side by side per slot
    (h[3q], h[3q+1], h[3q+2]) instead of three separate planes. A tap's 8-sample
    window then spans ~2 cache lines instead of 3, cutting L1D misses. NAMProf2
    measured 12,424 avg stall cycles left after the rings fit L2; with only a
    16 KB L1D, those are L1D misses served from L2. Same maths, same order."""
    old_sizes = [int(x) for x in re.search(r'static const unsigned nam_sizes\[\] = \{([0-9,]+)\};', h).group(1).split(',')]
    assert len(old_sizes) == N_LAYERS
    assert all(o >= n for o, n in zip(old_sizes, NEED)), 'existing rings smaller than required?'
    old_hist, new_hist = history_floats_pow2(old_sizes), history_floats_exact(interleave)

    h = _once(h, '#define NAM_BLOCK_KERNEL 1\n',
              '#define NAM_BLOCK_KERNEL 1\n#define NAM_EXACT_RINGS 1\n', 'NAM_BLOCK_KERNEL')
    h = _once(h, f'float v[30],sum[30],z[30],history[{old_hist}]; }} NamState;',
              f'unsigned lpos[{LPOS_SLOTS}];\n float v[30],sum[30],z[30],history[{new_hist}]; }} NamState;',
              'NamState history')
    h = re.sub(r'static const unsigned nam_sizes\[\] = \{[0-9,]+\};',
               'static const unsigned nam_sizes[] = {' + ','.join(map(str, NEED)) + '};', h, count=1)
    if interleave:
        h = _once(h, '        unsigned stride=n+2;\n',
                  '        unsigned stride=(3u*(n+8u)+1u)&~1u;   /* interleaved: 3 floats/slot, +8 mirror slots */\n', 'stride')
    else:
        h = _once(h, '        unsigned stride=n+2;\n',
                  '        unsigned stride=(n+9u)&~1u;   /* ring + 8-float mirror, kept even */\n', 'stride')
    h = _once(h, '        float * restrict h=history+off;\n',
              '        float * restrict h=history+off;\n'
              '        unsigned base=s->lpos[layer];\n'
              '        if(base>=n)base=0;          /* guard: never index outside the ring */\n',
              'layer prologue')
    h = _once(h, WRITE_OLD, WRITE_NEW_IL if interleave else WRITE_NEW, 'history write loop')
    h = _once(h, '            float w5=w[5],w6=w[6],w7=w[7],w8=w[8];\n',
              '            float w5=w[5],w6=w[6],w7=w[7],w8=w[8];\n'
              '            unsigned st0=base+n-(k-1-t)*d;if(st0>=n)st0-=n;   /* one wrap per tap */\n',
              'tap coefficient load')
    if interleave:
        h = _once(h, '                q=(pos+i-(k-1-t)*d)&(n-1);\n                float a=h[q],c=h[stride+q],e=h[2*stride+q];\n',
                  '                q=3u*(st0+i);             /* interleaved; may run into the mirror */\n'
                  '                float a=h[q],c=h[q+1],e=h[q+2];\n', 'history read (interleaved)')
    else:
        h = _once(h, '                q=(pos+i-(k-1-t)*d)&(n-1);\n',
                  '                q=st0+i;                  /* may run into the mirror; never wraps */\n',
                  'history read index')
    h = _once(h, '        w=b+18;off+=3*stride;\n',
              '        base+=count;if(base>=n)base-=n;s->lpos[layer]=base;\n'
              + ('        w=b+18;off+=stride;\n' if interleave else '        w=b+18;off+=3*stride;\n'),
              'layer epilogue')
    if regacc:
        assert interleave, 'register accumulators are written for the interleaved layout'
        h = _once(h, TAP_OLD_IL, _regacc_block(extra_counts=extra_counts, extra_group=extra_group), 'tap loop (for register accumulators)')
    assert '&(n-1)' not in h, 'a power-of-two wrap survived'
    return h


def apply(out: Path, interleave: bool = False, regacc: bool = False, extra_counts=(), extra_group=None) -> dict:
    """Transform nam_kernel_pedal.h and nam_kernel.c in a generate_block output dir."""
    out = Path(out)
    hp = out / 'nam_kernel_pedal.h'
    old = hp.read_text()
    new = transform(old, interleave, regacc, extra_counts, extra_group)
    hp.write_text(new)
    kc = out / 'nam_kernel.c'
    src = kc.read_text()
    suffix = src[src.index('unsigned nam_state_bytes'):]
    old_sizes = [int(x) for x in re.search(r'nam_sizes\[\] = \{([0-9,]+)\}', old).group(1).split(',')]
    old_hist, new_hist = history_floats_pow2(old_sizes), history_floats_exact(interleave)
    # host reset: zero the per-layer positions, and clear exactly the NEW history
    # length (the generator baked in the old count, now past the array's end)
    suffix = _once(suffix, 's->pos=0;', 's->pos=0;for(i=0;i<%d;i++)s->lpos[i]=0;' % LPOS_SLOTS, 'host reset')
    suffix = _once(suffix, f'i<{old_hist};', f'i<{new_hist};', 'host history clear')
    kc.write_text(new + '\n' + suffix)
    return dict(history_before=old_hist, history_after=new_hist)
