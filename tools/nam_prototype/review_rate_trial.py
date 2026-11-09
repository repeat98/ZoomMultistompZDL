#!/usr/bin/env python3
"""Isolate the current N/8 wrapper resampling from neural behavior.

Reproduces namlite.c input averaging/output interpolation using a unity network.
Eight-second periodic sine signals avoid FFT leakage and initialization effects.
Reports coloration/spurs of this conversion only, NOT actual capture response.
Run with numpy; results go to the ignored build directory.
"""
import json
from pathlib import Path
import numpy as np
fs=44100;length=fs*8;t=np.arange(length)/fs
results={}
for n in (4,5,6,7):
 positions=(np.arange(n)*8)//n
 info={'rate_hz':fs*n/8,'input_sample_centers':(positions+.5).tolist(),'network_warm_steps':8192*n//8,'identity_resampling':{}}
 for hz in (1000,4000,8000,16000):
  x=np.sin(2*np.pi*hz*t).reshape(-1,8)
  y=.5*(x[:,positions]+x[:,np.minimum(positions+1,7)])
  prev=np.roll(y[:,-1],1)
  sequence=np.column_stack((prev,y));q=(np.arange(8)+1)*n;idx=q//8;frac=(q%8)/8
  out=sequence[:,idx]+frac*(sequence[:,np.minimum(idx+1,n)]-sequence[:,idx])
  spectrum=abs(np.fft.rfft(out.ravel()))*2/length;bin0=hz*8
  main=float(spectrum[bin0]);spectrum[max(0,bin0-2):bin0+3]=0
  spur=int(np.argmax(spectrum));peak=float(spectrum[spur])
  info['identity_resampling'][hz]={'fundamental_db':float(20*np.log10(max(main,1e-20))),'largest_other_frequency_hz':spur/8,'largest_other_db_relative_to_input':float(20*np.log10(max(peak,1e-20)))}
 results[n]=info
out=Path(__file__).resolve().parents[2]/'build/probes/namlite/rate-review';out.mkdir(exist_ok=True)
(out/'resampling-review.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
