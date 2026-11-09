import ctypes as C,json,subprocess,time
from pathlib import Path
import numpy as np
from scipy.signal import fftconvolve,firwin,upfirdn
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];OUT=ROOT/'build/probes/slo-ir'
subprocess.run(['cc','-O2','-ffp-contract=off','-shared','-fPIC','-DHOST_TEST',str(HERE/'slo_ir.c'),'-I'+str(OUT),'-I'+str(ROOT/'src/airwindows/common'),'-o',str(OUT/'host.so')],check=True)
l=C.CDLL(str(OUT/'host.so'));ptr=C.POINTER(C.c_float);l.engine_bytes.restype=C.c_uint;l.slo_bytes.restype=C.c_uint;l.engine_process.argtypes=[C.c_void_p,ptr,ptr,C.c_uint];l.engine_overruns.argtypes=[C.c_void_p]
size=l.engine_bytes();h=np.load(OUT/'prepared.npz')['h'];f=firwin(65,4500,fs=44100);N=540672
report={'engine_bytes':size,'wrapper_bytes':l.slo_bytes(),'signals':{}}
for name in ['impulse','noise']:
 x=np.zeros(N,np.float32)
 if name=='impulse':x[0]=.5;x[450000]=-.25 # exercises history wrapping
 else:x[:88200]=np.random.default_rng(11).uniform(-.1,.1,88200)
 mem=(C.c_ubyte*(size+64))();C.memset(mem,0xA5,size+64);s=C.addressof(mem)+32;C.memset(s,0,size);y=np.zeros(N,np.float32)
 start=time.perf_counter();l.engine_process(s,x.ctypes.data_as(ptr),y.ctypes.data_as(ptr),N);elapsed=time.perf_counter()-start
 assert bytes(mem[:32])==bytes([0xA5])*32 and bytes(mem[-32:])==bytes([0xA5])*32
 assert l.engine_overruns(s)==0
 low=fftconvolve(x,f)[::4];wet=fftconvolve(low,h);wet=np.pad(wet,(512,0));reference=upfirdn(f*4,wet,up=4)[:N]
 error=float(np.max(abs(y-reference)));rms=float(np.sqrt(np.mean((y-reference)**2)));power=float(np.sqrt(np.mean(reference**2)))
 assert np.isfinite(y).all() and error<2e-4,(name,error)
 report['signals'][name]=dict(max_error=error,snr_db=float(20*np.log10(power/rms)),scheduler_overruns=0,host_seconds=elapsed)
report['note']='Host reference and work-budget checks; no TI cycle timing or pedal load verification.'
(OUT/'validation.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
