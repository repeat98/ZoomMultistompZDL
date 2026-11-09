"""Host checks of custom tape voicing; these do not emulate the Zoom ABI."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(shutil.which('cc'),'host compiler required')
class TapeVoicing(unittest.TestCase):
    def run_c(self,code,includes=()):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'test.c';exe=Path(td)/'test'
            src.write_text(code)
            subprocess.run(['cc','-std=c99','-O2','-Wno-unknown-pragmas','-I',str(ROOT),*[a for p in includes for a in ('-I',str(p))],str(src),'-o',str(exe)],check=True,capture_output=True)
            return subprocess.check_output([str(exe)],text=True)
    def test_control_ranges(self):
        self.run_c('''#include <assert.h>
#include "src/airwindows/common/tape_controls.h"
int main(void){
 float prev=0;
 for(int i=0;i<=1000;i++){
   float f=spool_feedback(i/1000.f);assert(f>=prev);assert(f<=1.40001f);prev=f;
 }
 assert(spool_feedback(0)==0);assert(spool_feedback(.8f)<.8f);
 assert(spool_feedback(.9f)<1);assert(spool_feedback(.95f)>1);
 assert(oxide_drive_denominator(0)==1);assert(oxide_drive_denominator(1)==1);
 assert(4/oxide_drive_denominator(4)<1.24f);
 return 0;
}''')
    def test_spool_impulse_and_high_feedback_stay_bounded(self):
        self.run_c('''#include <assert.h>
#include <stdlib.h>
#include "src/airwindows/tapeecho4/tapeecho4.c"
int main(void){
 TapeEcho4State *st=calloc(1,sizeof(*st));assert(st);
 for(int run=0;run<4;run++){
   for(unsigned i=0;i<sizeof(*st);i++)((unsigned char*)st)[i]=0;
   te4_finish_init(st);
   float feed=spool_feedback(run<2?.8f:1.f),wear=(run&1)?1.f:0.f;
   float late=0;
   for(int i=0;i<441000;i++){
     float l=i==0?.5f:0,r=l;
     te4_process_sample(st,&l,&r,1000.f,feed,0,0,wear,0,0,1);
     assert(l==l && r==r && l>-4 && l<4 && r>-4 && r<4);
     if(i>400000)late+=l*l;
   }
   if(run<2)assert(late<.0001f);
 }
 free(st);return 0;
}''')
    def test_oxide_actual_full_kernel_level_compensation(self):
        # Bypass only firmware pointer decoding: run the unchanged active kernel
        # with host pointers and its real initialized persistent state.
        path=ROOT/'src/airwindows/totape9/totape9.c';s=path.read_text()
        prefix=s[:s.index('void TOTAPE9_AUDIO_FUNC(unsigned int *ctx)')]
        body=s[s.index('    float rawInput = params[TOTAPE9_INPUT_SLOT];'):]
        body=body.rsplit('#endif',1)[0]+'}\n'
        harness='''\n#include <stdio.h>
#include <stdlib.h>
int main(void){
 for(int setting=0;setting<3;setting++){
  ToTape9State *st=calloc(1,sizeof(*st));start_lazy_init(st);
  while(!st->initialized)clear_state_chunk(st);
  float params[14]={1,0,0,0,1,.5,.5,.5,0,.5,.5,0,.5,1};
  params[5]=.5f+setting*.25f;
  double energy=0;float peak=0;
  for(int b=0;b<12000;b++){
   float samples[16];
   for(int k=0;k<8;k++){int t=(b*8+k)%100;float x=(t<50?t:100-t)*.008f-.2f;samples[k]=samples[k+8]=x;}
   host_process(params,samples,st);
   for(int k=0;k<8;k++){float v=samples[k];if(!(v==v && v>-2 && v<2))return 2;
    if(b>1000)energy+=(double)v*v;if(v<0)v=-v;if(v>peak)peak=v;}
  }
  printf("%g %g\\n",energy,peak);free(st);
 }return 0;
}'''
        code=prefix+'void host_process(float *params,float *fxBuf,ToTape9State *st){\n'+body+harness
        before=code.replace('if (inputGain > 1.0f) outputGain *= recip_approx_pos(oxide_drive_denominator(inputGain));','/* comparison: no compensation */')
        after_rows=[list(map(float,r.split())) for r in self.run_c(code,[path.parent]).splitlines()]
        before_rows=[list(map(float,r.split())) for r in self.run_c(before,[path.parent]).splitlines()]
        self.assertAlmostEqual(after_rows[0][0],before_rows[0][0],places=4)
        for i in (1,2):self.assertLess(after_rows[i][0],before_rows[i][0])
        print('Oxide host energy (Input 50/75/100), before:',before_rows,'after:',after_rows)
