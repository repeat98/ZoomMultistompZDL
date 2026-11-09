#include <stdint.h>
#include "zoom_params.h"
#include "engine.h"
#define MAGIC 0x534c4f31u
typedef struct {unsigned magic,clear,ready,pad;float mix,level,tone,lp;IREngine e;} SloState;
#pragma CODE_SECTION(Fx_REV_SloIR,".audio")
void Fx_REV_SloIR(uintptr_t *ctx){
 float *params=(float*)ctx[1],*fx=(float*)ctx[5];uintptr_t *d=(uintptr_t*)ctx[3];unsigned i;
 unsigned *src=(unsigned*)ctx[12],*dst=*(unsigned**)ctx[11];*dst=*src;
 if(!d||!d[0]||d[1]<=d[0]||d[1]-d[0]<8)return;
 uintptr_t base=(d[0]+7)&~(uintptr_t)7;if(d[1]-base<sizeof(SloState))return;SloState *s=(SloState*)base;
 if(params[0]<.5f){if(s->magic==MAGIC)s->magic=0;return;}
 if(s->magic!=MAGIC){s->magic=MAGIC;s->clear=0;s->ready=0;s->mix=0;s->level=1;s->lp=0;}
 if(!s->ready){unsigned stop=s->clear+2048;if(stop>sizeof(IREngine))stop=sizeof(IREngine);unsigned char *b=(unsigned char*)&s->e;for(i=s->clear;i<stop;i++)b[i]=0;s->clear=stop;if(stop==sizeof(IREngine))s->ready=1;return;}
 float gain=zoom_param_norm01(params[6],.5f);
 float mix=zoom_param_norm01(params[5],.5f),level=8*gain*gain*gain,tone=.03f+.97f*zoom_param_norm01(params[7],1);
 for(i=0;i<8;i++){
  float l=fx[i],r=fx[i+8],y=ir_sample(&s->e,(l+r)*.5f);
  s->mix+=.002f*(mix-s->mix);s->level+=.002f*(level-s->level);s->lp+=tone*(y-s->lp);y=s->lp*s->level;
  if(!(y>=-16 && y<=16)){s->magic=0;return;}if(y>1)y=1;if(y< -1)y=-1;
  fx[i]=l+s->mix*(y-l);fx[i+8]=r+s->mix*(y-r);
 }
 ir_work(&s->e,1024);
 if(s->e.overruns)s->magic=0;
}
#ifdef HOST_TEST
unsigned slo_bytes(void){return sizeof(SloState);}
unsigned engine_bytes(void){return sizeof(IREngine);}
void engine_process(IREngine *s,const float *in,float *out,unsigned n){unsigned i;for(i=0;i<n;i++){out[i]=ir_sample(s,in[i]);if((i&7)==7)ir_work(s,1024);}}
unsigned engine_overruns(IREngine *s){return s->overruns;}
#endif
