"""Audited release selectors; raw ranges preserve the existing patch ABI.

Mode thresholds use float32 UI*0.01, matching shared edit handlers, then the
comparisons in the DSP. Do not infer discrete controls from small max alone.
"""
import struct

def f32(v): return struct.unpack('<f',struct.pack('<f',v))[0]
def normalized(raw): return f32(raw*f32(.01))
def ladder(raw,limits): return sum(normalized(raw)>=f32(x) for x in limits)
def groups(labels, classify, maximum=100):
    result=[]
    for raw in range(maximum+1):
        label=labels[classify(raw)]
        if not result or result[-1]['label']!=label:
            result.append({'label':label,'from':raw,'to':raw,'value':raw})
        else: result[-1]['to']=raw
    for g in result: g['value']=(g['from']+g['to'])//2
    return result

SELECTORS={
 'Tonic':{
   'Mode':groups(['Decim','Crush','FM','Ring'],lambda r:ladder(r,[.25,.5,.75])),
   'Order':groups(['Fwd','Rev'],lambda r:ladder(r,[.5])),
 },
 'Rooms6':{'Mode':groups(['Room','Digit','Peak','Gate','Wave','Gong'],lambda r:r,5)},
 'Rooms':{'Mode':groups(['Room','Digit','Peak','Gate','Wave','Gong'],lambda r:min(5,int(f32(normalized(r)*f32(5.999)))))},
 'Spool':{'Div':groups(['1/16','1/8T','1/8','1/8.','1/4','1/4.'],lambda r:ladder(r,[.16666667,.33333334,.5,.6666667,.8333333]))},
 'Hydra':{'Div':groups(['Grain','1/32','1/16T','1/16','1/8T','1/8','1/8.','1/4'],lambda r:ladder(r,[.0625,.1875,.3125,.4375,.5625,.6875,.8125]))},
 'Spiral':{'Div':groups(['1/32','1/16T','1/16','1/8T','1/8','1/8.','1/4','1/4.'],lambda r:ladder(r,[.125,.25,.375,.5,.625,.75,.875]))},
 'Rewire':{'Route':groups(['BDRCS','SCRDB','DSBCR','RCSBD','SBRDC'],lambda r:ladder(r,[.2,.4,.6,.8]))},
 'Stasis':{'Capture':groups(['Stomp','Release','Hold'],lambda r:r,2)},
 'RndmFLTR':{
   'Type':groups(['HPF','BPF','LPF'],lambda r:r,2),
   'Chara':groups(['2Pole','4Pole'],lambda r:r,1),
 },
}
def attach_selectors(effect):
    for p in effect['params']:
        choices=SELECTORS.get(effect['name'],{}).get(p['name'])
        if choices and choices[-1]['to']==p['max']:
            p['choices']=choices
    return effect

def pedal_label(label):
    return {'Release':'Rels', 'Stomp':'Stmp'}.get(label,label)

def pedal_label_c(manifest):
    """Stock GetString ABI: A4=integer value, B4=destination; return length.

    Values use at most five ASCII chars to fit a pedal column; the copy is
    bounded to the stock eight-byte string buffer. Enabled for release builds
    after the Stasis hardware confirmation.
    """
    import json
    lines=[]
    for i,p in enumerate(manifest['params']):
        choices=SELECTORS.get(manifest['effect_name'],{}).get(p['name'])
        if not choices: continue
        if choices[-1]['to']!=p['max']: raise ValueError('selector range mismatch')
        lines += [f'int ZDL_GetLabel_{i}(unsigned int value, char *out) {{',
                  '    const char *s; int i;']
        for j,c in enumerate(choices):
            label=pedal_label(c['label'])
            assert len(label.encode('ascii'))<=5
            if j==len(choices)-1: prefix='else'
            else: prefix=('if' if j==0 else 'else if')+f' (value <= {c["to"]}u)'
            lines.append(f'    {prefix} s = {json.dumps(label)};')
        lines += ['    for (i=0; i<7; ++i) { out[i]=s[i]; if (!s[i]) return i; }',
                  '    out[7]=0; return 7;', '}']
    return '\n'.join(lines)
