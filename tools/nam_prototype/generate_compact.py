#!/usr/bin/env python3
"""A2 Lite loop kernel with read-only weights instead of unrolled immediates."""
import argparse
import json
from pathlib import Path
import numpy as np
from generate import load, generate, K, D


def compact(path, out):
    out = Path(out)
    generate(path, out)
    _, _, pre, layers, head, bias, scale = load(path)
    weights = list(pre)
    for cw, b, mix, rw, rb in layers:
        weights.extend(cw.transpose(2,0,1).ravel())
        weights.extend(b); weights.extend(mix); weights.extend(rw.ravel()); weights.extend(rb)
    weights.extend(head.ravel()); weights.extend([bias,scale])
    assert len(weights) == 1871
    sizes = [1 << ((k-1)*d).bit_length() for k,d in zip(K,D)]
    history = 3*sum(sizes)+48
    f = lambda x: format(float(x), '.9e')+'f'
    declarations = [
        f'typedef struct {{ unsigned pos; float history[{history}]; }} NamState;',
        'static const float nam_weights[] = {'+','.join(map(f,weights))+'};',
        'static const unsigned nam_dilations[] = {'+','.join(map(str,D))+'};',
        'static const unsigned nam_kernels[] = {'+','.join(map(str,K))+'};',
        'static const unsigned nam_sizes[] = {'+','.join(map(str,sizes))+'};',
    ]
    body = r'''
#pragma FUNC_ALWAYS_INLINE(nam_sample)
static inline float nam_sample(NamState *s,float x)
{
    const float *w=nam_weights;
    float v0=x*w[0],v1=x*w[1],v2=x*w[2];
    float sum0=0,sum1=0,sum2=0,y;
    unsigned layer,off=0,t,p,q;
    w+=3;
    for(layer=0;layer<23;layer++) {
        unsigned n=nam_sizes[layer],k=nam_kernels[layer],d=nam_dilations[layer];
        float *h=s->history+off;
        const float *b=w+9*k;
        float z0=b[0],z1=b[1],z2=b[2];
        p=s->pos&(n-1);
        h[3*p]=v0;h[3*p+1]=v1;h[3*p+2]=v2;
        for(t=0;t<k;t++) {
            float a,c,e;
            q=(p-(k-1-t)*d)&(n-1);
            a=h[3*q];c=h[3*q+1];e=h[3*q+2];
            z0+=w[0]*a;z0+=w[1]*c;z0+=w[2]*e;
            z1+=w[3]*a;z1+=w[4]*c;z1+=w[5]*e;
            z2+=w[6]*a;z2+=w[7]*c;z2+=w[8]*e;
            w+=9;
        }
        z0+=b[3]*x;z1+=b[4]*x;z2+=b[5]*x;
        if(z0<0)z0*=0.01f;
        if(z1<0)z1*=0.01f;
        if(z2<0)z2*=0.01f;
        sum0+=z0;sum1+=z1;sum2+=z2;
        v0+=b[15]+b[6]*z0+b[7]*z1+b[8]*z2;
        v1+=b[16]+b[9]*z0+b[10]*z1+b[11]*z2;
        v2+=b[17]+b[12]*z0+b[13]*z1+b[14]*z2;
        w=b+18;off+=3*n;
    }
    p=s->pos&15u;
    s->history[off+3*p]=sum0;
    s->history[off+3*p+1]=sum1;
    s->history[off+3*p+2]=sum2;
    y=w[48];
    for(t=0;t<16;t++) {
        q=off+3*((p-(15-t))&15u);
        y+=w[t]*s->history[q];
        y+=w[16+t]*s->history[q+1];
        y+=w[32+t]*s->history[q+2];
    }
    s->pos++;
    return y*w[49];
}
'''
    header='\n'.join(declarations)+'\n'+body
    (out/'nam_kernel_pedal.h').write_text(header)
    host=header+f'''
unsigned nam_state_bytes(void){{return sizeof(NamState);}}
void nam_reset(NamState *s){{unsigned i;s->pos=0;for(i=0;i<{history};i++)s->history[i]=0;}}
void nam_process(NamState *s,const float *in,float *out,unsigned n){{unsigned i;for(i=0;i<n;i++)out[i]=nam_sample(s,in[i]);}}
'''
    (out/'nam_kernel.c').write_text(host)
    report=json.loads((out/'geometry.json').read_text())
    report['representation']='compact loops and read-only coefficients'
    (out/'geometry.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model');p.add_argument('output');a=p.parse_args();compact(a.model,a.output)
