#include <stdint.h>
#define WORDS 33332u
#define MAGIC 0x4e4d454du
/* Exactly the NAM wrapper's133360-byte footprint:32-byte header +133328. */
typedef struct {unsigned magic,at,epoch,failed,stage,phase,tick,pad;volatile unsigned words[WORDS];} State;
#pragma FUNC_ALWAYS_INLINE(pattern)
static inline unsigned pattern(unsigned i,unsigned e){return (i*0x9e3779b9u)^(e*0x85ebca6bu)^0xa5963c69u;}
#pragma CODE_SECTION(Fx_FLT_NAMMem,".audio")
void Fx_FLT_NAMMem(uintptr_t *ctx){
 unsigned *src=(unsigned*)ctx[12],*dst=*(unsigned**)ctx[11];*dst=*src;
 float *p=(float*)ctx[1],*fx=(float*)ctx[5];uintptr_t *d=(uintptr_t*)ctx[3];unsigned j,code;
 if(p[0]<.5f)return;
 /* Inadequate arena: dry-through; cannot safely retain a beep counter. */
 if(!d||!d[0]||d[1]<=d[0]||d[1]-d[0]<8)return;
 uintptr_t base=(d[0]+7)&~(uintptr_t)7;if(d[1]-base<sizeof(State))return;State *s=(State*)base;
 /* LineSel edits divide raw values by100 even for a0/1 switch. */
 if(p[5]<.005f){s->magic=0;return;}
 if(s->magic!=MAGIC){s->magic=MAGIC;s->at=0;s->epoch=1;s->failed=0;s->stage=0;s->phase=0;s->tick=0;}
 if(s->at>=WORDS||s->stage>2){s->failed=1;s->at=0;s->stage=0;s->epoch=1;}
 for(j=0;j<32 && s->at<WORDS;j++,s->at++){
  unsigned at=s->at;
  if(!s->stage)s->words[at]=pattern(at,1);
  else {if(s->words[at]!=pattern(at,s->epoch))s->failed=1;s->words[at]=pattern(at,s->epoch+1);}
 }
 if(s->at==WORDS){s->at=0;if(!s->stage)s->stage=1;else {s->epoch++;s->stage=2;}}
 code=s->failed?4:(s->stage==2?2:1);
 for(j=0;j<8;j++){
  unsigned t=s->tick,phase=s->phase;float v=(phase<32?(float)phase:(float)(64-phase))*(1.0f/16)-1;
  unsigned pulse=t/8820u,within=t-pulse*8820u;
  float envelope=within<2205u?(float)(2205u-within)*(1.0f/2205):0;
  float tone=pulse<code?.025f*v*envelope:0;
  fx[j]=.8f*fx[j]+tone;fx[j+8]=.8f*fx[j+8]+tone;
  s->phase=(phase+1)&63;s->tick=t+1;if(s->tick==88200)s->tick=0;
 }
}
#ifdef HOST_TEST
unsigned probe_bytes(void){return sizeof(State);}
#endif
