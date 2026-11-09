"""Run the production Stasis block kernel with host-owned instance buffers."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(shutil.which('cc'), 'host C compiler required')
class Stasis(unittest.TestCase):
    def test_independent_capture_and_audio_contract(self):
        path=ROOT/'src/custom/stasis/stasis.c'
        source=path.read_text()
        prefix=source[:source.index('void STASIS_AUDIO_FUNC')]
        body=source[source.index('    if (st->magic != SS_MAGIC'):]
        code=prefix+'void process(float *params, float *fxBuf, StasisState *st, float *buf){\n'+body+r'''
#include <assert.h>
#include <stdlib.h>
#include <math.h>
typedef struct {StasisState st; float buf[SS_BUF]; float p[16];} Instance;
static Instance inst[4];
void block(int n,float left,float right,float *out){
 for(int k=0;k<8;k++){out[k]=left;out[k+8]=right;}
 process(inst[n].p,out,&inst[n].st,inst[n].buf);
 for(int k=0;k<16;k++)assert(isfinite(out[k]));
}
int main(void){
 float out[16];
 for(int n=0;n<4;n++){
  inst[n].p[0]=1; inst[n].p[5]=.35;inst[n].p[6]=.5;
  inst[n].p[7]=1;inst[n].p[8]=.55;inst[n].p[9]=1;
  inst[n].p[10]=.01; /* explicit live */
  for(int b=0;b<10000;b++){
   block(n,.1f*(n+1),-.03f,out);
   assert(out[0]==.1f*(n+1) && out[8]==-.03f);
  }
  assert(!inst[n].st.frozen);
 }
 /* Capture three distinct layers; bypass bounces must preserve each. */
 for(int n=0;n<3;n++){
  inst[n].p[10]=.02;
  for(int b=0;b<100;b++)block(n,.8,-.7,out);
  assert(inst[n].st.frozen && inst[n].st.gate==1);
  float expected=(.1f*(n+1)-.03f)*.5f*.9f;
  assert(fabsf(out[0]-expected)<.00001f && out[0]==out[8]);
  inst[n].p[0]=0;block(n,-.8,.9,out);inst[n].p[0]=1;block(n,-.8,.9,out);
  assert(inst[n].st.frozen && fabsf(out[0]-expected)<.00001f);
 }
 /* Record their sum into the fourth, then release the original three. */
 for(int b=0;b<10000;b++){
  float sum=0;
  for(int n=0;n<3;n++){block(n,0,0,out);sum+=out[0];}
  block(3,sum,sum,out);
 }
 inst[3].p[10]=.02;
 for(int b=0;b<100;b++)block(3,0,0,out);
 float held=out[0];assert(held>.1f);
 for(int n=0;n<3;n++){
  inst[n].p[10]=.01;
  for(int b=0;b<10000;b++)block(n,.4,-.2,out);
  assert(!inst[n].st.frozen && out[0]==.4f && out[8]==-.2f);
  /* Each later instance can capture again. */
  inst[n].p[10]=.02;
  for(int b=0;b<100;b++)block(n,0,0,out);
  assert(fabsf(out[0]-.09f)<.00001f);
 }
 for(int b=0;b<10000;b++){block(3,.8,-.7,out);assert(fabsf(out[0]-held)<.00001f);}
 /* The seam must never read history outside the selected capture window. */
 Instance *seam=&inst[2];seam->p[5]=0;seam->p[6]=1;
 seam->st.capEnd=10000;seam->st.pos=10000-SS_CAP_MIN;
 seam->st.lp=.18f;seam->st.level=1;seam->st.gate=1;
 for(int k=0;k<SS_BUF;k++)seam->buf[k]=-.8f;
 for(int k=10000-SS_CAP_MIN;k<10000;k++)seam->buf[k]=.2f;
 for(int b=0;b<3000;b++){block(2,0,0,out);assert(fabsf(out[0]-.18f)<.00001f);}
 /* Mix zero remains exactly stereo while frozen. */
 inst[3].p[9]=0;block(3,.2,-.6,out);assert(out[0]==.2f && out[8]==-.6f);
 /* A saved Hold value starts idle; stomp mode still works. */
 Instance *x=&inst[0];x->st.magic=0;x->p[10]=.02;block(0,.1,.2,out);assert(!x->st.frozen);
 x->p[10]=0;x->p[0]=0;block(0,.1,.2,out);
 x->p[0]=1;block(0,.1,.2,out);assert(x->st.frozen);
 x->p[0]=0;for(int b=0;b<100;b++)block(0,.1,.2,out);assert(!x->st.frozen && out[0]==.1f);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'stasis.c';exe=Path(td)/'stasis';c.write_text(code)
            subprocess.run(['cc','-std=c99','-O2','-Wno-unknown-pragmas','-I',str(path.parent),str(c),'-o',str(exe)],check=True,capture_output=True)
            subprocess.run([str(exe)],check=True)
