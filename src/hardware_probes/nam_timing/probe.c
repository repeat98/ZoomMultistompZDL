#include <stdint.h>
#include "measured_core.h"
#ifdef HOST_TEST
static unsigned fake_ticks,fake_step;
static unsigned clock_read(void){unsigned v=fake_ticks;fake_ticks+=fake_step;return v;}
#else
#include <c6x.h>
#pragma FUNC_ALWAYS_INLINE(clock_read)
static inline unsigned clock_read(void){return TSCL;}
#endif
#define TIME_MAGIC 0x4e544931u
typedef struct {unsigned magic,stage,calls,last,elapsed,total,peak,period,average,tick,phase;} Meter;
#pragma FUNC_ALWAYS_INLINE(bucket)
static inline unsigned bucket(unsigned ticks,unsigned period){
 if(!period)return 1;
 if(ticks<period/2)return 2;
 if(ticks<period-period/5)return 3;
 if(ticks<period)return 4;
 return 5;
}
#pragma CODE_SECTION(Fx_FLT_NAMTime,".audio")
void Fx_FLT_NAMTime(uintptr_t *ctx){
 unsigned *src=(unsigned*)ctx[12],*dst=*(unsigned**)ctx[11];*dst=*src;
 uintptr_t *d=(uintptr_t*)ctx[3];float *p=(float*)ctx[1],*fx=(float*)ctx[5];unsigned i,now=clock_read();
 if(!d||!d[0]||d[1]<=d[0]||d[1]-d[0]<8)return;
 uintptr_t base=(d[0]+7)&~(uintptr_t)7;if(d[1]-base<sizeof(PedalNam)+sizeof(Meter))return;
 PedalNam *net=(PedalNam*)base;Meter *m=(Meter*)(base+sizeof(PedalNam));
 if(p[0]<.5f){m->magic=0;return;}
 if(m->magic!=TIME_MAGIC){m->magic=TIME_MAGIC;m->stage=0;m->calls=0;m->last=now;m->elapsed=0;m->total=0;m->peak=0;m->period=0;m->tick=0;m->phase=0;net->magic=0;return;}
 if(m->stage==0){
  m->elapsed+=now-m->last;m->last=now;
  if(++m->calls==4096){m->period=m->elapsed>>12;m->calls=0;m->stage=m->period?1:3;m->average=0;}
  return;
 }
 if(m->stage==1||m->stage==2){
  unsigned start=clock_read();nam_core(ctx);unsigned cost=clock_read()-start;
  if(m->stage==1){if(net->ready&&net->warm==8192){m->stage=2;m->calls=0;}return;}
  m->total=cost>0xffffffffu-m->total?0xffffffffu:m->total+cost;
  if(cost>m->peak)m->peak=cost;
  if(++m->calls==4096){m->average=m->total>>12;m->stage=3;}
  return;
 }
 /* Alternating low/high groups encode mean/max observed elapsed core time.
  * Reporting is dry-through with quiet tones; the neural core is parked. */
 unsigned high=m->tick>=132300,code=bucket(high?m->peak:m->average,m->period);
 unsigned t=high?m->tick-132300:m->tick,pulse=t/8820,within=t-pulse*8820;
 for(i=0;i<8;i++){
  unsigned phase=m->phase;float v=(phase<32?(float)phase:(float)(64-phase))*(1.0f/16)-1;
  float env=within<2205?(float)(2205-within)*(1.0f/2205):0;
  float tone=pulse<code?.025f*v*env:0;fx[i]=.8f*fx[i]+tone;fx[i+8]=.8f*fx[i+8]+tone;
  m->phase=(phase+(high?2:1))&63;if(++m->tick==264600)m->tick=0;within++;
 }
}
#ifdef HOST_TEST
unsigned timing_bytes(void){return sizeof(PedalNam)+sizeof(Meter);}
unsigned net_bytes(void){return sizeof(PedalNam);}
void set_clock(unsigned v){fake_ticks=v;}
void set_step(unsigned v){fake_step=v;}
unsigned bucket_test(unsigned a,unsigned b){return bucket(a,b);}
#endif
