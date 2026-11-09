#!/usr/bin/env python3
"""Block/layer-major A2 Lite kernel; exact equations, planar history rings."""
import argparse,json
from pathlib import Path
from generate_compact import compact
from generate import K,D

def generate_block(model,out,inner_unroll=1):
    if inner_unroll not in (1,2):
        raise ValueError('Supported tap-loop unroll factors: 1 or 2')
    out=Path(out);compact(model,out)
    original=(out/'nam_kernel_pedal.h').read_text()
    constants=original[original.index('static const float nam_weights'):original.index('#pragma FUNC_ALWAYS_INLINE')]
    sizes=[1<<(((k-1)*d+8)-1).bit_length() for k,d in zip(K,D)]
    start=constants.index('static const unsigned nam_sizes[]')
    constants=constants[:start]+'static const unsigned nam_sizes[] = {'+','.join(map(str,sizes))+'};\n'
    # Two padding floats keep channel planes in different C674x memory banks.
    history=3*sum(n+2 for n in sizes)+3*34
    header=f'''#define NAM_BLOCK_KERNEL 1
typedef struct {{ unsigned pos,pad; float input[8],output[8],gain[8];
 float v[30],sum[30],z[30],history[{history}]; }} NamState;
'''+constants+r'''
#pragma FUNC_ALWAYS_INLINE(nam_block)
static inline void nam_block(NamState *s,unsigned count)
{
    const float * restrict w=nam_weights;
    const float * restrict input=s->input;
    float * restrict output=s->output;
    float * restrict v=s->v;
    float * restrict sum=s->sum;
    float * restrict zbuf=s->z;
    float * restrict history=s->history;
    unsigned pos=s->pos;
    unsigned i,layer,t,off=0,p,q;
    for(i=0;i<count;i++) {
        float x=s->input[i];
        s->v[i]=x*w[0];s->v[8+i]=x*w[1];s->v[16+i]=x*w[2];
        s->sum[i]=0;s->sum[8+i]=0;s->sum[16+i]=0;
    }
    w+=3;
    for(layer=0;layer<23;layer++) {
        unsigned n=nam_sizes[layer],k=nam_kernels[layer],d=nam_dilations[layer];
        float *h=s->history+off;
        const float *b=w+9*k;
        for(i=0;i<count;i++) {
            p=(s->pos+i)&(n-1);
            h[p]=s->v[i];h[n+p]=s->v[8+i];h[2*n+p]=s->v[16+i];
            s->z[i]=b[0];s->z[8+i]=b[1];s->z[16+i]=b[2];
        }
        /* Each coefficient set is reused across the whole block. Ring capacity
         * includes the extra seven future frames written above. */
        for(t=0;t<k;t++) {
            float w0=w[0],w1=w[1],w2=w[2],w3=w[3],w4=w[4];
            float w5=w[5],w6=w[6],w7=w[7],w8=w[8];
            for(i=0;i<count;i++) {
                q=(s->pos+i-(k-1-t)*d)&(n-1);
                float a=h[q],c=h[n+q],e=h[2*n+q];
                float z0=s->z[i],z1=s->z[8+i],z2=s->z[16+i];
                z0+=w0*a;z0+=w1*c;z0+=w2*e;
                z1+=w3*a;z1+=w4*c;z1+=w5*e;
                z2+=w6*a;z2+=w7*c;z2+=w8*e;
                s->z[i]=z0;s->z[8+i]=z1;s->z[16+i]=z2;
            }
            w+=9;
        }
        for(i=0;i<count;i++) {
            float x=s->input[i];
            float z0=s->z[i]+b[3]*x,z1=s->z[8+i]+b[4]*x,z2=s->z[16+i]+b[5]*x;
            if(z0<0)z0*=.01f;if(z1<0)z1*=.01f;if(z2<0)z2*=.01f;
            s->sum[i]+=z0;s->sum[8+i]+=z1;s->sum[16+i]+=z2;
            s->v[i]+=b[15]+b[6]*z0+b[7]*z1+b[8]*z2;
            s->v[8+i]+=b[16]+b[9]*z0+b[10]*z1+b[11]*z2;
            s->v[16+i]+=b[17]+b[12]*z0+b[13]*z1+b[14]*z2;
        }
        w=b+18;off+=3*n;
    }
    for(i=0;i<count;i++) {
        p=(s->pos+i)&31u;
        s->history[off+p]=s->sum[i];s->history[off+32+p]=s->sum[8+i];
        s->history[off+64+p]=s->sum[16+i];s->output[i]=w[48];
    }
    for(t=0;t<16;t++) {
        float w0=w[t],w1=w[16+t],w2=w[32+t];
        for(i=0;i<count;i++) {
            q=off+((s->pos+i-(15-t))&31u);
            float y=s->output[i];
            y+=w0*s->history[q];y+=w1*s->history[q+32];y+=w2*s->history[q+64];
            s->output[i]=y;
        }
    }
    for(i=0;i<count;i++)s->output[i]*=w[49];
    s->pos+=count;
}
'''
    # Expose genuinely disjoint scratch/history regions to the TI scheduler.
    # Without this, dynamic history offsets force conservative load/store order.
    for field,replacement in [('input','input'),('output','output'),('v','v'),('sum','sum'),('z','zbuf'),('history','history')]:
        header=header.replace('s->'+field+'[',replacement+'[')
    header=header.replace('[8+i]','[10+i]').replace('[16+i]','[20+i]')
    header=header.replace('d=nam_dilations[layer];','d=nam_dilations[layer];\n        unsigned stride=n+2;')
    header=header.replace('h[n+','h[stride+').replace('h[2*n+','h[2*stride+')
    header=header.replace('off+=3*n;', 'off+=3*stride;')
    header=header.replace('off+32+p','off+34+p').replace('off+64+p','off+68+p')
    header=header.replace('q+32','q+34').replace('q+64','q+68')
    header=header.replace('float *h=s->history+off;', 'float * restrict h=history+off;')
    header=header.replace('(s->pos+i', '(pos+i')
    if inner_unroll == 2:
        header=header.replace('            for(i=0;i<count;i++) {',
                              '            #pragma UNROLL(2)\n            for(i=0;i<count;i++) {')
    (out/'nam_kernel_pedal.h').write_text(header)
    host=header+f'''
unsigned nam_state_bytes(void){{return sizeof(NamState);}}
void nam_reset(NamState *s){{unsigned i;s->pos=0;for(i=0;i<{history};i++)s->history[i]=0;}}
void nam_process(NamState *s,const float *in,float *out,unsigned n){{
 unsigned at=0,i,count;
 while(at<n){{count=n-at;if(count>8)count=8;
  for(i=0;i<count;i++)s->input[i]=in[at+i];
  nam_block(s,count);
  for(i=0;i<count;i++)out[at+i]=s->output[i];at+=count;
 }}
}}
'''
    (out/'nam_kernel.c').write_text(host)
    r=json.loads((out/'geometry.json').read_text())
    r.update(state_bytes=8+4*(114+history),representation='layer-major eight-frame blocks; planar padded history',history_floats=history)
    (out/'geometry.json').write_text(json.dumps(r,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('model');p.add_argument('out');a=p.parse_args();generate_block(a.model,a.out)
