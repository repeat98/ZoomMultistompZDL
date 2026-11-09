/* Incremental real-signal partitioned convolution, Q15 spectra / float sums.
 * Work advances by a fixed count per eight-frame audio callback.
 */
#include "ir_data.h"
#ifdef __TI_COMPILER_VERSION__
#include <c6x.h>
#endif
#pragma FUNC_ALWAYS_INLINE(ir_recip)
static inline float ir_recip(float x){
#ifdef __TI_COMPILER_VERSION__
 float r=_rcpsp(x);r=r*(2-x*r);return r*(2-x*r);
#else
 return 1.0f/x;
#endif
}
typedef struct {
 float input[2][256],out[2][256],overlap[256],re[512],im[512];
 short history[IR_PARTS*257*2];
 float scale[IR_PARTS],down[65],up[17];
 unsigned input_page,out_page,at,job,read_page,write_page;
 unsigned phase,cursor,len,part,bin,history_pos,completed,overruns;
 unsigned dp,up_pos,decim;
 float peak,quant_scale,tail;
} IREngine;
#pragma FUNC_ALWAYS_INLINE(ir_reverse)
static inline unsigned ir_reverse(unsigned x){
 unsigned r=0,i;for(i=0;i<9;i++){r=(r<<1)|(x&1);x>>=1;}return r;
}
#pragma FUNC_ALWAYS_INLINE(ir_start)
static inline void ir_start(IREngine *s){
 if(s->phase){s->overruns++;return;}
 if(s->completed){s->out_page=s->write_page;s->completed=0;}
 s->write_page=1-s->out_page;s->read_page=s->input_page;s->input_page=1-s->input_page;
 s->phase=1;s->cursor=0;s->peak=0;
}
#pragma FUNC_ALWAYS_INLINE(ir_work)
static inline void ir_work(IREngine *s,unsigned budget){
 unsigned work;
 for(work=0;work<budget && s->phase;work++){
  unsigned i=s->cursor;
  if(s->phase==1){
   unsigned r=ir_reverse(i);s->re[r]=i<256?s->input[s->read_page][i]:0;s->im[r]=0;
   if(++s->cursor==512){s->phase=2;s->cursor=0;s->len=1;}
  }else if(s->phase==2 || s->phase==8){
   unsigned half=1u<<(s->len-1),j=i&(half-1),a=(i>>(s->len-1))*(half*2)+j,b=a+half,t=j<<(9-s->len);
   float c=ir_cos[t],v=(s->phase==2?-ir_sin[t]:ir_sin[t]);
   float r=c*s->re[b]-v*s->im[b],im=c*s->im[b]+v*s->re[b];
   s->re[b]=s->re[a]-r;s->im[b]=s->im[a]-im;s->re[a]+=r;s->im[a]+=im;
   if(++s->cursor==256){s->cursor=0;++s->len;if(s->len>9)s->phase=s->phase==2?3:9;}
  }else if(s->phase==3){
   float r=s->re[i],im=s->im[i];if(r<0)r=-r;if(im<0)im=-im;
   if(r>s->peak)s->peak=r;if(im>s->peak)s->peak=im;
   if(++s->cursor==257){s->quant_scale=s->peak>1e-20f?s->peak*3.0518509476e-5f:1.0f;s->scale[s->history_pos]=s->quant_scale;s->phase=4;s->cursor=0;}
  }else if(s->phase==4){
   unsigned off=(s->history_pos*257+i)*2;
   float inv=ir_recip(s->quant_scale);float r=s->re[i]*inv,im=s->im[i]*inv;
   if(r>32767)r=32767;if(r< -32767)r=-32767;if(im>32767)im=32767;if(im< -32767)im=-32767;
   s->history[off]=(short)(r>=0?r+.5f:r-.5f);s->history[off+1]=(short)(im>=0?im+.5f:im-.5f);
   s->re[i]=0;s->im[i]=0;
   if(++s->cursor==257){s->phase=5;s->cursor=0;s->part=0;s->bin=0;}
  }else if(s->phase==5){
   unsigned h=s->history_pos+IR_PARTS-s->part;if(h>=IR_PARTS)h-=IR_PARTS;
   unsigned a=(s->part*257+s->bin)*2,b=(h*257+s->bin)*2;
   float scale=ir_scale[s->part]*s->scale[h];
   float ar=ir_bank[a],ai=ir_bank[a+1],br=s->history[b],bi=s->history[b+1];
   s->re[s->bin]+=(ar*br-ai*bi)*scale;s->im[s->bin]+=(ar*bi+ai*br)*scale;
   if(++s->bin==257){s->bin=0;if(++s->part==IR_PARTS){s->phase=6;s->cursor=257;}}
  }else if(s->phase==6){
   s->re[i]=s->re[512-i];s->im[i]=-s->im[512-i];
   if(++s->cursor==512){s->phase=7;s->cursor=0;}
  }else if(s->phase==7){
   unsigned r=ir_reverse(i);if(r>i){float tmp=s->re[i];s->re[i]=s->re[r];s->re[r]=tmp;tmp=s->im[i];s->im[i]=s->im[r];s->im[r]=tmp;}
   if(++s->cursor==512){s->phase=8;s->cursor=0;s->len=1;}
  }else{
   s->out[s->write_page][i]=s->re[i]*(1.0f/512)+s->overlap[i];s->overlap[i]=s->re[i+256]*(1.0f/512);
   if(++s->cursor==256){s->phase=0;s->completed=1;if(++s->history_pos==IR_PARTS)s->history_pos=0;}
  }
 }
}
#pragma FUNC_ALWAYS_INLINE(ir_sample)
static inline float ir_sample(IREngine *s,float x){
 unsigned j,p;float wet=0;
 s->down[s->dp]=x;
 if(s->decim==0){
  float low=0;p=s->dp;
  for(j=0;j<65;j++){low+=s->down[p]*ir_filter[j];p=p?p-1:64;}
  s->input[s->input_page][s->at]=low;
  s->up[s->up_pos]=s->out[s->out_page][s->at];
  if(++s->at==256){s->at=0;ir_start(s);}
 }
 p=s->up_pos;
 for(j=s->decim;j<65;j+=4){wet+=s->up[p]*ir_filter[j]*4.0f;p=p?p-1:16;}
 if(++s->dp==65)s->dp=0;
 if(++s->decim==4){s->decim=0;if(++s->up_pos==17)s->up_pos=0;}
 return wet;
}
