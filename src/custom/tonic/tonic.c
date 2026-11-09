/* Tonic: independent Bitters-inspired topology, not an exact emulation.
 * ctx[5]: eight L samples then eight R samples. State is per instance.
 * No heap, writable globals, jump tables or external audio helpers. */
#include <stdint.h>
#include "../../airwindows/common/zoom_params.h"
#include "tonic_params.h"

#define MAGIC 0x544e4331u
#define SIZE 1024u
#define MASK (SIZE-1u)
#define PI2 6.283185307f
#define INLINE(f) ZOOM_ALWAYS_INLINE(f)
typedef struct {
    uint32_t magic, clear, pos;
    int mode, order, count, gateOpen;
    float amount, drive, phase, mix, fade;
    float lfo, carrier, vibrato, hold, envelope, gate;
    float feedback, ap[6], delay[SIZE];
} TonicState;

INLINE(flush)
static inline float flush(float x) { return (x<1e-18f && x>-1e-18f)?0:x; }
INLINE(clip)
static inline float clip(float x) {
    if(x>1)return 1; if(x< -1)return -1;
    return 1.5f*x-.5f*x*x*x;
}
INLINE(sine)
static inline float sine(float phase) {
    float x=phase*PI2;
    if(x>3.141592654f)x-=PI2;
    float y=1.27323954f*x-.405284735f*x*(x<0?-x:x);
    return y+.225f*(y*(y<0?-y:y)-y);
}
INLINE(drive)
static inline float drive(float x,float amount) {
    float fade=amount*20; if(fade>1)fade=1;
    float wet=clip(x*(1+30*amount*amount))*(.666666667f-.38f*amount);
    return x+fade*(wet-x);
}
INLINE(phaser)
static inline float phaser(float x,float amount,TonicState *s) {
    int i; float fade=amount*20; if(fade>1)fade=1;
    s->lfo+=(.02f+19.98f*amount*amount)*(1.f/44100.f);
    if(s->lfo>=1)s->lfo-=1;
    float a=-.90f+.85f*(.5f+.5f*sine(s->lfo));
    float y=x+.3f*s->feedback;
    for(i=0;i<6;i++) {
        float z=a*y+s->ap[i]; s->ap[i]=flush(y-a*z); y=z;
    }
    s->feedback=flush(clip(y));
    return x+fade*(.5f*(x+y)-x);
}
INLINE(processor)
static inline float processor(float x,float amount,TonicState *s) {
    float wet=x; int mode=s->mode;
    /* Populate delay even in other modes; mode changes reset it under dry fade. */
    s->delay[s->pos&MASK]=x;
    if(mode==0) {
        int hold=1+(int)(amount*amount*255);
        if(s->count<=0) {s->hold=x;s->count=hold;}
        s->count--;wet=s->hold;
    } else if(mode==1) {
        int bits=16-(int)(amount*15+.5f);
        float ax=x<0?-x:x;
        float envRate=ax>s->envelope?.2f:.001f;
        s->envelope=flush(s->envelope+envRate*(ax-s->envelope));
        if(s->envelope>.002f)s->gateOpen=1;
        if(s->envelope<.001f)s->gateOpen=0;
        s->gate+=.01f*((float)s->gateOpen-s->gate);
        if(bits<=1)wet=(x>=0?.5f:-.5f)*s->gate;
        else {
            /* Powers of two avoid table addresses or division helpers. */
            int levels=1<<(bits-1);
            union {uint32_t u;float f;} inv;
            inv.u=(uint32_t)(127-(bits-1))<<23;
            float bounded=x; if(bounded>1)bounded=1;if(bounded< -1)bounded=-1;
            float q=bounded*(float)levels;
            wet=(float)(int)(q+(q>=0?.5f:-.5f))*inv.f*s->gate;
        }
    } else if(mode==2) {
        s->vibrato+=(.2f+29.8f*amount*amount)*(1.f/44100.f);
        if(s->vibrato>=1)s->vibrato-=1;
        float depth=1+90*amount*amount;
        float delay=2+depth*(1+sine(s->vibrato));
        int whole=(int)delay;float frac=delay-(float)whole;
        uint32_t p=(s->pos-(uint32_t)whole)&MASK;
        wet=s->delay[p]+frac*(s->delay[(p-1)&MASK]-s->delay[p]);
    } else {
        s->carrier+=(20+3980*amount*amount)*(1.f/44100.f);
        if(s->carrier>=1)s->carrier-=1;
        wet=x*sine(s->carrier);
    }
    s->pos++;
    float fade=amount*20;if(fade>1)fade=1;
    return x+fade*(wet-x);
}

#pragma CODE_SECTION(Fx_DLY_Tonic, ".audio")
void Fx_DLY_Tonic(uintptr_t *ctx) {
    float *p=(float*)ctx[1],*fx=(float*)ctx[5];
    unsigned *src=(unsigned*)ctx[12],*dst=*(unsigned**)ctx[11];
    *dst=*src;
    uintptr_t *desc=(uintptr_t*)ctx[3];
    if(!desc)return;
    uintptr_t base=desc[0],end=desc[1];
    if(!base || end<=base || end-base<8)return;
    base+=(8-(base&7))&7;
    if(end-base<sizeof(TonicState))return;
    TonicState *s=(TonicState*)base;
    if(p[0]<.5f) {if(s->magic==MAGIC)s->fade=0;return;}
    float modeNorm=zoom_param_norm01(p[5],.12f);
    int mode=0;if(modeNorm>=.25f)mode=1;if(modeNorm>=.5f)mode=2;if(modeNorm>=.75f)mode=3;
    int order=zoom_param_norm01(p[9],0)>=.5f;
    float amount=zoom_param_norm01(p[6],.25f),dr=zoom_param_norm01(p[7],0);
    float ph=zoom_param_norm01(p[8],0),mix=zoom_param_norm01(p[10],.5f);
    int i;
    if(s->magic!=MAGIC) {
        s->magic=MAGIC;s->clear=0;s->pos=0;s->count=0;s->gateOpen=0;
        s->mode=mode;s->order=order;s->amount=amount;s->drive=dr;s->phase=ph;s->mix=mix;
        s->fade=0;s->lfo=0;s->carrier=0;s->vibrato=0;s->hold=0;
        s->envelope=0;s->gate=0;s->feedback=0;
        for(i=0;i<6;i++)s->ap[i]=0;
    }
    if(s->clear<SIZE) {
        uint32_t stop=s->clear+128;if(stop>SIZE)stop=SIZE;
        for(;s->clear<stop;s->clear++)s->delay[s->clear]=0;
        return;
    }
    /* Ramp to dry before switching mode/order, reset state, then ramp back. */
    int changing=(mode!=s->mode || order!=s->order);
    if(changing && s->fade<=0) {
        s->mode=mode;s->order=order;s->clear=0;s->count=0;s->hold=0;
        s->envelope=0;s->gate=0;s->gateOpen=0;s->feedback=0;
        for(i=0;i<6;i++)s->ap[i]=0;
        return;
    }
    for(i=0;i<8;i++) {
        float l=fx[i],r=fx[i+8],x=.5f*(l+r);
        s->amount+=.002f*(amount-s->amount);
        s->drive+=.002f*(dr-s->drive);s->phase+=.002f*(ph-s->phase);
        s->mix+=.002f*(mix-s->mix);
        if(amount==0 && s->amount<.00001f)s->amount=0;
        if(dr==0 && s->drive<.00001f)s->drive=0;
        if(ph==0 && s->phase<.00001f)s->phase=0;
        s->fade+=changing?-.002f:.002f;
        if(s->fade<0)s->fade=0;if(s->fade>1)s->fade=1;
        if(s->order==0) {
            x=drive(x,s->drive);x=phaser(x,s->phase,s);x=processor(x,s->amount,s);
        } else {
            x=processor(x,s->amount,s);x=phaser(x,s->phase,s);x=drive(x,s->drive);
        }
        /* Endpoint dry preserves L/R exactly, including state warmup. */
        float blend=s->mix*s->fade;
        if(mix==0)blend=0;
        if(mix==1 && s->mix>.99999f)blend=s->fade;
        if(s->amount==0 && s->drive==0 && s->phase==0)blend=0;
        if(blend>=1) {fx[i]=x;fx[i+8]=x;}
        else {fx[i]=l+blend*(x-l);fx[i+8]=r+blend*(x-r);}
    }
}
