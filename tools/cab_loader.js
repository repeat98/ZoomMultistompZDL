/* Cabinet IR -> CabIR bank. Browser and Node. No uploaded code is executed.
 *
 * Port of src/hardware_probes/cab_ir/fit.py (the reference): a cab IR becomes
 * a 32-tap FIR plus 6 biquads (HPF, LPF, 4 peaks) fitted to its 1/6-octave
 * magnitude, then written into the fixed CabIR engine template
 * (tools/cab_template, built by build.py --template). Only coefficient bytes
 * change; the audio code and its relocations are never touched. */
(function(root){
'use strict';
const SlotIdentity=typeof module!=='undefined'?require('./slot_identity.js'):root.SlotIdentity;
const CoverArt=typeof module!=='undefined'?require('./cover_art.js'):root.CoverArt;
const FS=44100,NFFT=1<<15,TAPS=32,PEAKS=4,NBQ=2+PEAKS;
function need(ok,message){if(!ok)throw Error(message);}

// ---- WAV -------------------------------------------------------------------
function parseWav(buffer){
 const v=new DataView(buffer instanceof ArrayBuffer?buffer:buffer.buffer.slice(buffer.byteOffset,buffer.byteOffset+buffer.byteLength));
 const tag=(o)=>String.fromCharCode(v.getUint8(o),v.getUint8(o+1),v.getUint8(o+2),v.getUint8(o+3));
 need(v.byteLength>=12&&tag(0)==='RIFF'&&tag(8)==='WAVE','This is not a WAV file.');
 let at=12,fmt=null,data=null;
 while(at+8<=v.byteLength){
  const id=tag(at),size=v.getUint32(at+4,true),body=at+8;
  if(id==='fmt '){let format=v.getUint16(body,true);if(format===0xFFFE&&size>=26)format=v.getUint16(body+24,true);
   fmt={format,channels:v.getUint16(body+2,true),rate:v.getUint32(body+4,true),bits:v.getUint16(body+14,true)};}
  else if(id==='data')data={at:body,size:Math.min(size,v.byteLength-body)};
  at=body+size+(size&1);
 }
 need(fmt&&data,'The WAV file has no audio.');
 need((fmt.format===1&&[16,24,32].includes(fmt.bits))||(fmt.format===3&&fmt.bits===32),'Use a 16/24/32-bit PCM or 32-bit float WAV.');
 need(fmt.channels>=1&&fmt.channels<=8,'Unsupported channel count.');
 need(fmt.rate===44100||fmt.rate===48000,'Use a 44.1 kHz or 48 kHz IR.');
 const step=fmt.bits/8,frames=Math.floor(data.size/(step*fmt.channels));
 need(frames>=16,'The IR is too short.');need(frames<=fmt.rate*2,'The IR is longer than 2 seconds; this is probably not a cabinet IR.');
 const out=new Float64Array(frames);
 for(let n=0;n<frames;n++){let s=0;
  for(let c=0;c<fmt.channels;c++){const o=data.at+(n*fmt.channels+c)*step;
   s+=fmt.format===3?v.getFloat32(o,true):fmt.bits===16?v.getInt16(o,true)/32768:fmt.bits===32?v.getInt32(o,true)/2147483648:
     (((v.getUint8(o)|(v.getUint8(o+1)<<8)|(v.getUint8(o+2)<<16))<<8)>>8)/8388608;}
  out[n]=s/fmt.channels;}
 need(out.every(Number.isFinite),'The WAV file contains invalid samples.');
 return {sampleRate:fmt.rate,samples:out};
}
// 48 -> 44.1 kHz: Kaiser-windowed sinc, cut just under the new Nyquist.
function resample48(x){
 const L=147,M=160,H=48,beta=8,fc=0.94*L/M,n=Math.ceil(x.length*L/M),y=new Float64Array(n);
 const i0=(z)=>{let s=1,t=1;for(let k=1;k<30;k++){t*=(z/(2*k))**2;s+=t;}return s;},norm=i0(beta);
 for(let j=0;j<n;j++){const t=j*M/L,c=Math.floor(t);let s=0;
  for(let k=c-H+1;k<=c+H;k++){if(k<0||k>=x.length)continue;const d=t-k,r=d/H;if(Math.abs(r)>=1)continue;
   const sinc=d===0?1:Math.sin(Math.PI*fc*d)/(Math.PI*fc*d);s+=x[k]*fc*sinc*i0(beta*Math.sqrt(1-r*r))/norm;}
  y[j]=s;}
 return y;
}
function prepare(wav){
 let x=wav.sampleRate===48000?resample48(wav.samples):Float64Array.from(wav.samples);
 let peak=0;for(const s of x)peak=Math.max(peak,Math.abs(s));need(peak>1e-6,'The IR is silent.');
 let first=0;while(first<x.length&&Math.abs(x[first])<=peak*1e-3)first++;
 return x.slice(Math.max(0,first-2));
}

// ---- spectra -----------------------------------------------------------------
function fftMag(x){        // |rfft(x, NFFT)|, radix-2
 const re=new Float64Array(NFFT),im=new Float64Array(NFFT);re.set(x.subarray(0,Math.min(x.length,NFFT)));
 for(let i=1,j=0;i<NFFT;i++){let b=NFFT>>1;for(;j&b;b>>=1)j^=b;j^=b;if(i<j){[re[i],re[j]]=[re[j],re[i]];}}
 for(let len=2;len<=NFFT;len<<=1){const a=-2*Math.PI/len,wr=Math.cos(a),wi=Math.sin(a);
  for(let i=0;i<NFFT;i+=len){let cr=1,ci=0;
   for(let k=0;k<len/2;k++){const p=i+k,q=p+len/2,tr=re[q]*cr-im[q]*ci,ti=re[q]*ci+im[q]*cr;
    re[q]=re[p]-tr;im[q]=im[p]-ti;re[p]+=tr;im[p]+=ti;const nr=cr*wr-ci*wi;ci=cr*wi+ci*wr;cr=nr;}}}
 const m=new Float64Array(NFFT/2+1);for(let k=0;k<=NFFT/2;k++)m[k]=Math.hypot(re[k],im[k]);return m;
}
const binFreq=(k)=>k*FS/NFFT;
function smoothDb(mag,frac){          // fractional-octave power average, as fit.smooth_db
 const n=mag.length,c=new Float64Array(n+1);for(let i=0;i<n;i++)c[i+1]=c[i]+mag[i]*mag[i];
 const k=2**(1/(2*frac)),out=new Float64Array(n),f=(i)=>i*FS/(2*(n-1));
 const search=(v)=>{let lo=0,hi=n;while(lo<hi){const m=(lo+hi)>>1;if(f(m)<v)lo=m+1;else hi=m;}return lo;};
 for(let i=0;i<n;i++){const lo=search(f(i)/k),hi=Math.max(lo+1,search(f(i)*k));out[i]=10*Math.log10(Math.max((c[hi]-c[lo])/(hi-lo),1e-20));}
 return out;
}
function interp(xs,full){const out=new Float64Array(xs.length);
 for(let i=0;i<xs.length;i++){const p=xs[i]*NFFT/FS,k=Math.floor(p),t=p-k;out[i]=k+1<full.length?full[k]*(1-t)+full[k+1]*t:full[full.length-1];}return out;}
const geom=(a,b,n)=>Float64Array.from({length:n},(_,i)=>a*(b/a)**(i/(n-1)));

// ---- biquads (RBJ), rows [b0,b1,b2,a1,a2] --------------------------------------
function row(b,a){return [b[0]/a[0],b[1]/a[0],b[2]/a[0],a[1]/a[0],a[2]/a[0]];}
function peak(f,g,q){const A=10**(g/40),w=2*Math.PI*f/FS,al=Math.sin(w)/(2*q);return row([1+al*A,-2*Math.cos(w),1-al*A],[1+al/A,-2*Math.cos(w),1-al/A]);}
function lowpass(f,q){const w=2*Math.PI*f/FS,al=Math.sin(w)/(2*q),c=Math.cos(w);return row([(1-c)/2,1-c,(1-c)/2],[1+al,-2*c,1-al]);}
function highpass(f,q){const w=2*Math.PI*f/FS,al=Math.sin(w)/(2*q),c=Math.cos(w);return row([(1+c)/2,-(1+c),(1+c)/2],[1+al,-2*c,1-al]);}
function build(p){const s=[highpass(Math.exp(p[0]),p[1]),lowpass(Math.exp(p[2]),p[3])];
 for(let i=0;i<PEAKS;i++)s.push(peak(Math.exp(p[4+3*i]),p[5+3*i],p[6+3*i]));return s;}
function responseDb(sos,fir,freqs){      // |cascade * FIR| in dB at freqs
 const out=new Float64Array(freqs.length);
 for(let i=0;i<freqs.length;i++){const w=2*Math.PI*freqs[i]/FS,c1=Math.cos(w),s1=Math.sin(w),c2=Math.cos(2*w),s2=Math.sin(2*w);let db=0;
  for(const [b0,b1,b2,a1,a2] of sos){const nr=b0+b1*c1+b2*c2,ni=-(b1*s1+b2*s2),dr=1+a1*c1+a2*c2,di=-(a1*s1+a2*s2);
   db+=10*Math.log10(Math.max((nr*nr+ni*ni)/(dr*dr+di*di),1e-24));}
  if(fir){let r=0,im=0;for(let t=0;t<fir.length;t++){r+=fir[t]*Math.cos(w*t);im-=fir[t]*Math.sin(w*t);}db+=10*Math.log10(Math.max(r*r+im*im,1e-18));}
  out[i]=db;}
 return out;
}

// ---- Levenberg-Marquardt with box bounds --------------------------------------
function solve(A,b){const n=b.length,M=A.map((r,i)=>[...r,b[i]]);
 for(let c=0;c<n;c++){let p=c;for(let r=c+1;r<n;r++)if(Math.abs(M[r][c])>Math.abs(M[p][c]))p=r;[M[c],M[p]]=[M[p],M[c]];
  if(Math.abs(M[c][c])<1e-300)return null;
  for(let r=c+1;r<n;r++){const f=M[r][c]/M[c][c];if(f)for(let k=c;k<=n;k++)M[r][k]-=f*M[c][k];}}
 const x=new Array(n).fill(0);for(let r=n-1;r>=0;r--){let s=M[r][n];for(let k=r+1;k<n;k++)s-=M[r][k]*x[k];x[r]=s/M[r][r];}return x;}
function lm(fun,p0,lo,hi,iters){
 let p=p0.map((v,i)=>Math.min(hi[i],Math.max(lo[i],v))),r=fun(p),cost=r.reduce((s,v)=>s+v*v,0),lambda=1e-3;
 for(let it=0;it<iters;it++){
  const J=p.map((v,i)=>{const h=1e-6*Math.max(1,Math.abs(v)),q=p.slice();q[i]=v+h<=hi[i]?v+h:v-h;const d=q[i]-v,rq=fun(q);return rq.map((x,k)=>(x-r[k])/d);});
  const n=p.length,A=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>{let s=0;for(let k=0;k<r.length;k++)s+=J[i][k]*J[j][k];return s;})),
   g=J.map(col=>{let s=0;for(let k=0;k<r.length;k++)s+=col[k]*r[k];return s;});
  let improved=false;
  for(let tries=0;tries<12;tries++){
   const B=A.map((rw,i)=>rw.map((v,j)=>i===j?v*(1+lambda)+1e-12:v)),d=solve(B,g.map(x=>-x));
   if(d){const q=p.map((v,i)=>Math.min(hi[i],Math.max(lo[i],v+d[i]))),rq=fun(q),c=rq.reduce((s,v)=>s+v*v,0);
    if(c<cost){const rel=(cost-c)/Math.max(cost,1e-30);p=q;r=rq;cost=c;lambda=Math.max(lambda/3,1e-9);improved=true;if(rel<1e-10)return p;break;}}
   lambda*=4;
  }
  if(!improved)break;
 }
 return p;
}

// ---- the fit (fit.fit) ----------------------------------------------------------
function fit(ir,opts={}){
 const mag=fftMag(ir),tgtFull=smoothDb(mag,6),grid=geom(40,18000,240),tgt=interp(grid,tgtFull);
 const w=grid.map(f=>f>10000?0.3:1),ref=Math.max(...tgt),t=tgt.map(v=>v-ref);
 let p=[Math.log(70),0.7,Math.log(5000),0.7],lo=[Math.log(20),0.3,Math.log(1500),0.3],hi=[Math.log(400),3,Math.log(16000),3];
 for(const f of [110,450,1500,3200]){p.push(Math.log(f),0,1);lo.push(Math.log(40),-24,0.2);hi.push(Math.log(12000),24,8);}
 const nb=p.length,resid=(q,fir)=>{const m=responseDb(build(q),fir,grid);return m.map((v,i)=>w[i]*(v-t[i]));};
 const unit=Array.from({length:TAPS},(_,i)=>i?0:1),start=opts.start??'both';
 const joint=(p0)=>lm(v=>resid(v.slice(0,nb),v.slice(nb)),[...p0,...unit],[...lo,...Array(TAPS).fill(-4)],[...hi,...Array(TAPS).fill(4)],opts.iters2??300);
 const costOf=(v)=>resid(v.slice(0,nb),v.slice(nb)).reduce((s,x)=>s+x*x,0);
 // Stage 1 (biquads alone) then the joint fit, and also the joint fit from the
 // untouched initial guess: they land in different minima, keep the better.
 const cands=[];
 if(start!=='raw')cands.push(joint(lm(q=>resid(q,null),p,lo,hi,opts.iters1??200)));
 if(start!=='staged')cands.push(joint(p));
 let q=cands.reduce((a,b)=>costOf(b)<costOf(a)?b:a);
 const sos=build(q.slice(0,nb)),fir=q.slice(nb);
 for(const [,, ,a1,a2] of sos){const f1=Math.fround(a1),f2=Math.fround(a2);need(Math.abs(f2)<1&&Math.abs(f1)<1+f2,'The fit produced an unstable filter. Try another IR.');}
 // Level: loudness-matched -- a pink (guitar-like) spectrum, 80 Hz-6 kHz,
 // comes out as loud as it went in. Normalising the PEAK (the low resonance)
 // to -3 dB, as 0.20 did, left real playing 7-9 dB quieter than the input.
 const band=geom(80,6000,400),bdb=responseDb(sos,fir,band);let pw=0;for(const v of bdb)pw+=10**(v/10);
 const loudness=10*Math.log10(pw/band.length),gain=10**(((opts.loudnessDb??0)-loudness)/20);
 // error report, as Fit.error_db: 1/3-octave, level offset removed, 80 Hz - 8 kHz
 const bins=Float64Array.from({length:NFFT/2+1},(_,k)=>Math.max(binFreq(k),1e-3)),modFull=responseDb(sos,fir,bins);
 const third=geom(40,18000,300),T=interp(third,smoothDb(mag,3)),Mm=interp(third,smoothDb(modFull.map(v=>10**(v/20)),3));
 const d=[];for(let i=0;i<third.length;i++)if(third[i]>=80&&third[i]<=8000)d.push(Mm[i]-T[i]);
 const mean=d.reduce((s,v)=>s+v,0)/d.length,dd=d.map(v=>v-mean);
 return {fir,sos,gain,errorDb:Math.sqrt(dd.reduce((s,v)=>s+v*v,0)/dd.length),worstDb:Math.max(...dd.map(Math.abs)),
  sourceMs:ir.length/FS*1000,plot:{freqs:Array.from(third),target:Array.from(T.map(v=>v-Math.max(...T))),model:Array.from(Mm.map(v=>v-Math.max(...Mm)))}};
}

// ---- slot writer (build.py fill_cab) --------------------------------------------
// One cab per effect file. Each of the template's slots is its own effect ID
// (FXID 930..945), like the NAM capture slots: a patch stores the ID, so a cab
// never changes under a patch. (0.20 put 8 cabs behind a Cab knob, and a patch
// stored the knob position -- reordering the bank changed what patches played.)
async function sha256(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
function checkCab(c,m){need(c&&Array.isArray(c.fir)&&c.fir.length===m.taps&&Array.isArray(c.sos)&&c.sos.length===m.biquads&&c.sos.every(r=>Array.isArray(r)&&r.length===5)&&Number.isFinite(c.gain),'Invalid cab data.');
 need([...c.fir,...c.sos.flat(),c.gain].every(v=>Number.isFinite(v)&&Number.isFinite(Math.fround(v))),'Cab coefficients out of range.');
 for(const [,, ,a1,a2] of c.sos){const f1=Math.fround(a1),f2=Math.fround(a2);need(Math.abs(f2)<1&&Math.abs(f1)<1+f2,'Unstable cab filter.');}}
// Starts with a letter (as NAM names): from slot 100 the slot takes three
// digits, so 'C10' + '0abc' must never read as slot 100's 'C100abc'.
function cabName(value){const name=String(value).trim();need(/^[a-zA-Z][a-zA-Z0-9_-]{0,7}$/.test(name),'Use 1-8 letters, numbers, hyphens or underscores for the cab name, starting with a letter.');return name;}
// The pedal shows at most 9 characters (stock names); 'CAB-' + 8 broke its screen (issue #5).
function pedalName(name){return 'CAB-'+cabName(name).slice(0,5);}
// C<2-digit slot><up to 5 chars of name>.ZDL, and C<3-digit slot><4 chars>
// from slot 100 -- at most 8 characters and unique per slot: the pedal
// truncates basenames to 8 and freezes on duplicates.
function fileName(slot,name){return 'C'+String(slot).padStart(2,'0')+cabName(name).slice(0,slot<100?5:4)+'.ZDL';}
// Cab slots: 1-16 are FXID 930-945 (shipped templates), 17-216 are 700-899,
// made from one base template (slot_identity.js). IDs are permanent.
function cabFxid(slot){return slot<=16?929+slot:683+slot;}
async function fillCab(template,manifest,slot,cab,name,icon){
 need(manifest.format===2&&manifest.taps===TAPS&&manifest.biquads===NBQ&&Array.isArray(manifest.slots),'Unsupported cab engine template.');
 let s;try{s=SlotIdentity.slotMeta(manifest,slot);}catch{s=null;}need(s&&s.fxid===cabFxid(slot),'No such cab slot.');
 // Slots past the shipped templates: `template` is the shared base; make this slot from it.
 if(s.generated){template=await SlotIdentity.generateSlot(template,manifest,slot,sha256);s={...s,bytes:template.length,sha256:await sha256(template)};}
 const original=new Uint8Array(template);
 need(original.length===s.bytes&&await sha256(original)===s.sha256,'The cab engine template is damaged or outdated. Reload the page.');
 const {fir_offset:fo,sos_offset:so,gain_offset:go,name_offset:no}=s,t=manifest.taps,b=manifest.biquads;
 need([fo,so,go,no].every(o=>Number.isInteger(o)&&o>=76)&&fo+4*t<=original.length&&so+20*b<=original.length&&go+4<=original.length&&no+12<=original.length,'Invalid cab engine offsets.');
 checkCab(cab,manifest);name=cabName(name);
 const out=original.slice(),v=new DataView(out.buffer);
 cab.fir.forEach((x,i)=>v.setFloat32(fo+4*i,x,true));
 cab.sos.forEach((r,j)=>r.forEach((x,k)=>v.setFloat32(so+4*(5*j+k),x,true)));
 v.setFloat32(go,cab.gain,true);
 out.fill(0,no,no+12);out.set(new TextEncoder().encode(pedalName(name)),no);
 if(manifest.cover){icon=icon||manifest.cover.default_icon;CoverArt.writeCover(out,s,manifest.cover,name,icon);}
 return {bytes:out,report:{engine:manifest.engine,version:manifest.output_version,slot,fxid:s.fxid,icon:icon||null,filename:fileName(slot,name),
  displayName:pedalName(name),name:'CabIR-'+name,source:cab.source||'',fitRmsDb:cab.errorDb,fitWorstDb:cab.worstDb,sha256:await sha256(out),engineSha256:s.sha256}};
}
// The browser's cabs: each keeps its slot for life (removing frees it; the
// next cab added takes the lowest free one), so patches never change cab.
const CABS_KEY='cabir-cabs-v1';
function readCabs(storage){try{const b=JSON.parse(storage.getItem(CABS_KEY)||'[]');return Array.isArray(b)?b.filter(c=>Number.isInteger(c.slot)&&c.slot>=1&&c.slot<=99&&typeof c.name==='string'):[];}catch{return [];}}
function saveCabs(storage,cabs){storage.setItem(CABS_KEY,JSON.stringify(cabs));}
function freeSlot(cabs,max){for(let s=1;s<=max;s++)if(!cabs.some(c=>c.slot===s))return s;return 0;}

const api={parseWav,resample48,prepare,fit,fillCab,fileName,cabFxid,cabName,pedalName,responseDb,peak,lowpass,highpass,readCabs,saveCabs,freeSlot,CABS_KEY,TAPS,NBQ};
if(typeof module!=='undefined')module.exports=api;else root.CabLoader=api;
})(globalThis);
