#!/usr/bin/env python3
"""Generate a fixed-shape mono A2 Lite C kernel. Experimental, no ZDL output."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
D=[1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239]
K=[6]*14+[15,15]+[6]*7

def load(path):
    root=json.loads(Path(path).read_text());m=root
    if root['architecture']=='SlimmableContainer':m=root['config']['submodels'][0]['model']
    assert m['architecture']=='WaveNet'
    cfg=m['config'];assert len(cfg['layers'])==1 and cfg['head'] is None
    l=cfg['layers'][0]
    assert (l['channels'],l['bottleneck'],l['input_size'],l['condition_size'])==(3,3,1,1)
    assert l['kernel_sizes']==K and l['dilations']==D
    assert l['head']=={'out_channels':1,'kernel_size':16,'bias':True}
    assert l['layer1x1']['active'] and l['layer1x1']['groups']==1
    assert not l['head1x1']['active'] and l['groups_input']==l['groups_input_mixin']==1
    assert l['gating_mode']==['none']*23 and all(a['type']=='LeakyReLU' and a['negative_slope']==.01 for a in l['activation'])
    assert not any(v.get('active',False) for k,v in l.items() if 'film' in k)
    w=np.asarray(m['weights'],np.float32);at=0
    def take(shape):
        nonlocal at
        n=int(np.prod(shape));v=w[at:at+n].reshape(shape);at+=n;return v
    pre=take((3,));layers=[]
    for k,d in zip(K,D):layers.append((take((3,3,k)),take((3,)),take((3,)),take((3,3)),take((3,))))
    head=take((3,16));bias=take((1,))[0];scale=take((1,))[0];assert at==len(w)
    return root,m,pre,layers,head,bias,scale

def generate(path,out):
    root,m,pre,layers,head,bias,scale=load(path)
    f=lambda x:format(float(x),'.9e')+'f'
    sizes=[1<<(((k-1)*d+1)-1).bit_length() for k,d in zip(K,D)]
    offsets=[];size=0
    for n in sizes:offsets.append(size);size+=3*n
    head_off=size;size+=48
    s=['/* Generated A2 Lite experiment. Weights supplied by user; not a release effect. */',
       f'typedef struct {{ unsigned pos; float history[{size}]; }} NamState;',
       'unsigned nam_state_bytes(void){return sizeof(NamState);}',
       'void nam_reset(NamState *s){unsigned i;s->pos=0;for(i=0;i<'+str(size)+';i++)s->history[i]=0;}',
       'typedef struct {float a,b,c,h0,h1,h2;} NamFrame;']
    for li,(cw,b,mix,rw,rb) in enumerate(layers):
        n=sizes[li];off=offsets[li];k=K[li];d=D[li]
        s += [f'static void layer_{li}(NamState *s,NamFrame *v,float x){{',f'unsigned p=s->pos & {n-1}u;',f'float *h=s->history+{off};', 'h[3*p]=v->a;h[3*p+1]=v->b;h[3*p+2]=v->c;',* [f'float z{i}={f(b[i])};' for i in range(3)]]
        for tap in range(k):
            s += ['{',f'unsigned q=(p-{(k-1-tap)*d}u)&{n-1}u;','float a=h[3*q],b=h[3*q+1],c=h[3*q+2];']
            for i in range(3):
                for j,t in enumerate(['a','b','c']):s.append(f'z{i}+={f(cw[i,j,tap])}*{t};')
            s+=['}']
        for i in range(3):s += [f'z{i}+={f(mix[i])}*x;',f'if(z{i}<0)z{i}*=0.01f;',f'v->h{i}+=z{i};']
        for i,t in enumerate(['a','b','c']):s.append(f'v->{t}+={f(rb[i])}+'+'+'.join(f'{f(rw[i,j])}*z{j}' for j in range(3))+';')
        s+=['}']
    s+=['float nam_sample(NamState *s,float x){','NamFrame v;',f'float *h=s->history+{head_off};', 'unsigned p=s->pos&15u;',f'float y={f(bias)};']
    for i,t in enumerate(['a','b','c']):s.append(f'v.{t}=x*{f(pre[i])};')
    s+=['v.h0=v.h1=v.h2=0;']+[f'layer_{i}(s,&v,x);' for i in range(23)]+['h[3*p]=v.h0;h[3*p+1]=v.h1;h[3*p+2]=v.h2;']
    for k in range(16):
        for j in range(3):s.append(f'y+={f(head[j,k])}*h[3*((p-{15-k}u)&15u)+{j}];')
    s+=['s->pos++;',f'return y*{f(scale)};','}', 'void nam_process(NamState *s,const float *in,float *out,unsigned n){unsigned i;for(i=0;i<n;i++)out[i]=nam_sample(s,in[i]);}']
    out=Path(out);out.mkdir(parents=True,exist_ok=True);(out/'nam_kernel.c').write_text('\n'.join(s)+'\n')
    (out/'lite.nam').write_text(json.dumps(dict(m,sample_rate=root['sample_rate'])))
    report=dict(model_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),sample_rate=root['sample_rate'],weights=len(m['weights']),state_bytes=4+size*4,macs_per_sample=3+sum(9*k+3+9 for k in K)+48+1,scope='Mono C kernel only. No pedal timing, rate conversion or ZDL release.')
    (out/'geometry.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('model');a.add_argument('output');v=a.parse_args();generate(v.model,v.output)
