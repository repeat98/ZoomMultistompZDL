#!/usr/bin/env python3
"""Validate all published WAVs; does not claim listening or hardware validation."""
import hashlib,json
from pathlib import Path
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[2]
rows=[]
for p in sorted((ROOT/'previews/audio').glob('*.wav')):
    a,sr=sf.read(p,always_2d=True)
    assert len(a)>0 and np.isfinite(a).all(),p
    peak=float(np.max(np.abs(a)));rms=float(np.sqrt(np.mean(a*a)))
    clipped=int(np.sum(np.abs(a)>=1-2**-23))
    assert peak>1e-6 and clipped==0,p
    rows.append(dict(file=p.name,sample_rate=sr,channels=a.shape[1],seconds=len(a)/sr,peak=peak,rms=rms,full_scale_samples=clipped,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
(ROOT/'previews/audio/validation.json').write_text(json.dumps({'checks':'decodable, finite, non-silent, no full-scale samples; not a listening review','files':rows},indent=2)+'\n')
print(f'{len(rows)} WAV files passed')
