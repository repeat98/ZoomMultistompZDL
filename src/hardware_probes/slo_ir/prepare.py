#!/usr/bin/env python3
"""Prepare the user-owned Slö wet tail for a bounded-work convolution prototype."""
import io,json,zipfile,hashlib
from pathlib import Path
import numpy as np,soundfile as sf
from scipy.signal import resample_poly,firwin
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'build/probes/slo-ir';OUT.mkdir(parents=True,exist_ok=True)
source=Path('/Users/themanro/Downloads/Walrus Audio Slo.zip')
with zipfile.ZipFile(source) as z:raw=z.read('Walrus Slo Dreaming.wav')
x,sr=sf.read(io.BytesIO(raw));assert sr==48000 and x.ndim==1
peak=int(np.argmax(abs(x)));wet=x[peak:].copy()
# This is an estimated direct/wet separation, not a separately captured wet IR.
wet[:480]=0;wet[480:576]*=np.linspace(0,1,96)
# Remove the final near-noise discontinuity without dropping tail duration.
wet[-2400:]*=np.linspace(1,0,2400)
h=resample_poly(wet,147,640).astype(np.float32) # 48 kHz -> 11.025 kHz
B=256;N=512;P=(len(h)+B-1)//B
padded=np.pad(h,(0,P*B-len(h))).reshape(P,B)
H=np.fft.rfft(np.pad(padded,((0,0),(0,B))),axis=1)
scales=np.maximum(np.max(np.maximum(abs(H.real),abs(H.imag)),axis=1)/32767,1e-20).astype(np.float32)
q=np.stack([np.rint(H.real/scales[:,None]),np.rint(H.imag/scales[:,None])],axis=-1).astype(np.int16)
reconstructed=q[:,:,0]*scales[:,None]+1j*q[:,:,1]*scales[:,None]
rh=np.fft.irfft(reconstructed,n=N,axis=1)
# Q15 spectra retain tiny second-half residuals; runtime overlap-add retains these too.
err=np.sqrt(np.mean(abs(reconstructed-H)**2));den=np.sqrt(np.mean(abs(H)**2))
sf.write(OUT/'wet-tail-11025.wav',h,11025,subtype='FLOAT')
np.savez(OUT/'prepared.npz',h=h,q=q,scales=scales)
flt=firwin(65,4500,fs=44100).astype(np.float32)
def arr(name,values,kind='float'):
 vals=np.asarray(values).ravel();fmt=(lambda v:format(float(v),'.9e')+'f') if kind=='float' else (lambda v:str(int(v)))
 return 'static const '+kind+' '+name+'[] = {\n'+','.join(map(fmt,vals))+'\n};\n'
header=f'#define IR_PARTS {P}\n#define IR_BINS 257\n#define IR_BLOCK 256\n#define IR_FFT 512\n'
header+=arr('ir_bank',q,'short')+arr('ir_scale',scales)
header+=arr('ir_cos',np.cos(2*np.pi*np.arange(256)/512))+arr('ir_sin',np.sin(2*np.pi*np.arange(256)/512))+arr('ir_filter',flt)
(OUT/'ir_data.h').write_text(header)
report=dict(source_sha256=hashlib.sha256(raw).hexdigest(),source_frames=len(x),source_rate=sr,direct_peak_frame=peak,removed_alignment_ms=peak/sr*1000,direct_removal_ms=10,wet_rate=11025,wet_frames=len(h),wet_seconds=len(h)/11025,partitions=P,spectral_bank_bytes=q.nbytes+scales.nbytes,spectral_quantization_snr_db=float(20*np.log10(den/err)),wet_latency_ms=512/11025*1000+64/44100*1000,limitations=['Estimated direct removal; first 10ms muted, next 2ms faded','Wet bandwidth limited by 4.5kHz resampling filters','Last 50ms faded; full remaining tail duration retained','Static IR does not reproduce live Slö modulation/sustain'])
(OUT/'preparation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
