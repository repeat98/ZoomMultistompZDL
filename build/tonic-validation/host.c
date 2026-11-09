#include "/Users/themanro/ZoomMultistompZDL/src/custom/tonic/tonic.c"

unsigned tonic_state_bytes(void){return sizeof(TonicState);}
void tonic_render(uintptr_t *ctx,const float *input,float *output,unsigned n){
 float block[16];ctx[5]=(uintptr_t)block;
 for(unsigned j=0;j<n;j+=8){
  for(unsigned i=0;i<8;i++){block[i]=input[2*(j+i)];block[i+8]=input[2*(j+i)+1];}
  Fx_DLY_Tonic(ctx);
  for(unsigned i=0;i<8;i++){output[2*(j+i)]=block[i];output[2*(j+i)+1]=block[i+8];}
 }
}
