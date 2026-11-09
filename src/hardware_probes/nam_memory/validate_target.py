"""Check the actual ZDL at legal Test values0/1, not percent-style100."""
import argparse,json,subprocess
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser();p.add_argument('namcheck',type=Path);a=p.parse_args();out=Path(__file__).resolve().parents[3]/'build/probes/nam-memory'
np.zeros(176400,np.float32).tofile(out/'target-silence.f32')
for knob in (0,1):
 dest=out/f'target-test-{knob}.f32'
 with (out/f'target-test-{knob}.log').open('w') as log:subprocess.run([str(a.namcheck),str(out/'NAMMem.ZDL'),str(out/'target-silence.f32'),str(dest),str(knob)],stdout=log,stderr=log,check=True)
 x=np.fromfile(dest,np.float32);assert len(x)==176400 and np.isfinite(x).all()
 if knob==0:assert not np.any(x)
 else:
  groups=x[88200:].reshape(10,8820);active=np.max(abs(groups),axis=1)>1e-5
  assert np.array_equal(active,[True,True]+[False]*8),active
(out/'target-validation.json').write_text(json.dumps({'passed':True,'checks':['Test0 produces silence','Test1 produces exactly two passing beeps after initialization','actual init/edit/audio machine code; no unsupported instructions'],'hardware':'pending'},indent=2)+'\n')
print('Actual target Test0/1 and two-beep pattern verified.')
