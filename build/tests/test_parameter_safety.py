"""Host endpoint checks and malformed TI object rejection."""
import contextlib
import io
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import linker
ROOT=Path(__file__).resolve().parents[2]
TI=Path('/Applications/ti/ti-cgt-c6000_8.5.0.LTS/bin/cl6x')
class Parameters(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'),'host C compiler required')
    def test_endpoints_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'params.c';exe=Path(td)/'params'
            src.write_text('''#include <assert.h>
#include <math.h>
#include "src/airwindows/common/zoom_params.h"
int main(void){
 assert(zoom_param_norm01(0,.5f)==0);
 assert(zoom_param_norm01(.01f,.5f)==.01f);
 assert(zoom_param_norm01(.5f,.1f)==.5f);
 assert(zoom_param_norm01(1,.5f)==1);
 assert(zoom_param_norm01(NAN,.5f)==.5f);
 assert(zoom_param_norm01(INFINITY,.5f)==.5f);
 assert(zoom_param_norm01(-1,.5f)==.5f);
 assert(zoom_param_norm(0,.5f)==0);
 assert(zoom_param_switch(0,1)==0);
 for(int i=0;i<=100;i++){float x=i/100.f;assert(zoom_param_norm01(x,.5f)==x);}
 return 0;
}''')
            subprocess.run(['cc','-std=c99','-Wno-unknown-pragmas','-I',str(ROOT),str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
@unittest.skipUnless(TI.exists(),'TI C6000 compiler required')
class Relocations(unittest.TestCase):
    def check_bad_object(self,unknown):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);src=td/'bad.c';obj=td/'bad.obj';out=td/'bad.ZDL'
            src.write_text('\n#pragma CODE_SECTION(Fx_FLT_Bad,".audio")\nextern float absent(float);\nfloat Fx_FLT_Bad(float x){return absent(x);}\n')
            subprocess.run([str(TI),'--c99','-mv6740','--abi=eabi','--mem_model:data=far','--opt_level=2','--gen_func_subsections=off','-c',str(src),f'--output_file={obj}'],cwd=td,check=True,capture_output=True)
            # Normalize the compiler's function subsection to the linker input section.
            obj.write_bytes(obj.read_bytes().replace(b'.audio:Fx_FLT_Bad\0', b'.audio\0' + bytes(len(b':Fx_FLT_Bad'))))
            if unknown:
                parsed=linker.ObjFile(obj);data=bytearray(obj.read_bytes())
                target=next(i for i,s in enumerate(parsed.symbols) if s['name']=='Fx_FLT_Bad')
                audio=next(s for s in parsed.sections if s['name']=='.audio')
                rel=next(s for s in parsed.sections if s['type'] in (linker.SHT_REL,linker.SHT_RELA) and s['info']==audio['idx'])
                struct.pack_into('<I',data,rel['offset']+4,(target<<8)|255);obj.write_bytes(data)
            cfg=linker.LinkerConfig(effect_name='Bad',gid=1,fxid=123,params=[],obj_path=obj,output_path=out)
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'unsupported relocation' if unknown else 'unresolved relocation'):
                    linker.link(cfg)
            self.assertFalse(out.exists())
    def test_unresolved_executable_reference(self):self.check_bad_object(False)
    def test_unknown_relocation(self):self.check_bad_object(True)
