const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const C=require('../cab_loader.js');
const base=path.join(__dirname,'..'),manifest=JSON.parse(fs.readFileSync(path.join(base,'cab_template/cab.json')));
const tpl=s=>fs.readFileSync(path.join(base,'cab_template',manifest.slots[s-1].file));

function wav(samples,{rate=48000,channels=1,bits=16,float=false}={}){
 const frames=samples.length/channels,step=bits/8,data=Buffer.alloc(frames*channels*step);
 samples.forEach((s,i)=>{const o=i*step;if(float)data.writeFloatLE(s,o);else if(bits===16)data.writeInt16LE(Math.round(s*32767),o);
  else if(bits===24)data.writeIntLE(Math.round(s*8388607),o,3);else data.writeInt32LE(Math.round(s*2147483647),o);});
 const h=Buffer.alloc(44);h.write('RIFF',0);h.writeUInt32LE(36+data.length,4);h.write('WAVE',8);h.write('fmt ',12);h.writeUInt32LE(16,16);
 h.writeUInt16LE(float?3:1,20);h.writeUInt16LE(channels,22);h.writeUInt32LE(rate,24);h.writeUInt32LE(rate*channels*step,28);h.writeUInt16LE(channels*step,32);
 h.writeUInt16LE(bits,34);h.write('data',36);h.writeUInt32LE(data.length,40);return Buffer.concat([h,data]);
}
// A synthetic "cab": known filters driven by an impulse. No commercial IR in the repo.
function synthCab(){
 const sos=[C.highpass(85,0.8),C.lowpass(4800,0.9),C.peak(130,5,1.2),C.peak(700,-4,1.1),C.peak(2500,4,1.6),C.peak(5200,-6,2)];
 let x=new Float64Array(900);x[3]=1;
 for(const [b0,b1,b2,a1,a2] of sos){let z0=0,z1=0;x=x.map(u=>{const o=b0*u+z0;z0=b1*u-a1*o+z1;z1=b2*u-a2*o;return o;});}
 return x;
}

test('WAV: 16/24/32-bit PCM and float, stereo mixed to mono, rates checked',()=>{
 const s=Array.from({length:400},(_,i)=>0.5*Math.sin(i/7));
 for(const o of [{bits:16},{bits:24},{bits:32},{bits:32,float:true}]){const w=C.parseWav(wav(s,o));assert.equal(w.sampleRate,48000);assert.ok(Math.abs(w.samples[10]-s[10])<1e-4,JSON.stringify(o));}
 const st=C.parseWav(wav(s.flatMap(v=>[v,-v]),{channels:2}));assert.ok(Math.abs(st.samples[5])<1e-4);
 assert.throws(()=>C.parseWav(wav(s,{rate:96000})),/44\.1 kHz or 48 kHz/);
 assert.throws(()=>C.parseWav(Buffer.from('not a wav at all')),/not a WAV/);
});

test('48 -> 44.1 kHz resampling keeps a tone at its frequency and level',()=>{
 const f=1000,x=Float64Array.from({length:48000},(_,i)=>Math.sin(2*Math.PI*f*i/48000)),y=C.resample48(x);
 assert.ok(Math.abs(y.length-44100)<=1);
 let re=0,im=0;for(let i=2000;i<42000;i++){re+=y[i]*Math.cos(2*Math.PI*f*i/44100);im+=y[i]*Math.sin(2*Math.PI*f*i/44100);}
 assert.ok(Math.abs(2*Math.hypot(re,im)/40000-1)<0.01);
});

test('fit reproduces a synthetic cab within 0.6 dB and yields stable float32 filters',()=>{
 const r=C.fit(synthCab(),{start:'staged'});
 assert.equal(r.fir.length,32);assert.equal(r.sos.length,6);assert.ok(r.errorDb<0.6,`rms ${r.errorDb}`);
 for(const [,, ,a1,a2] of r.sos){assert.ok(Math.abs(Math.fround(a2))<1&&Math.abs(Math.fround(a1))<1+Math.fround(a2));}
 assert.ok(Number.isFinite(r.gain)&&r.gain>0);
});

test('filenames: <= 8 characters and unique for every slot and legal name',()=>{
 const all=new Set();
 for(const s of manifest.slots)for(const name of ['a','sm57','mesaV30x','Z-9_']){const f=C.fileName(s.slot,name);assert.match(f,/^C\d\d[A-Za-z0-9_-]{1,5}\.ZDL$/);assert.ok(f.length-4<=8,f);all.add(s.slot+':'+f.slice(0,3));}
 assert.equal(new Set(manifest.slots.map(s=>C.fileName(s.slot,'x').slice(0,3))).size,manifest.slots.length,'slot prefixes collide');
 assert.ok(manifest.slots.length>=16);assert.deepEqual(manifest.slots.map(s=>s.fxid),manifest.slots.map(s=>929+s.slot));
 for(const bad of ['','123456789','../x','a b'])assert.throws(()=>C.fileName(1,bad));
});

test('slot writer: only coefficient and name bytes change; template and cab checked',async()=>{
 const r=C.fit(synthCab(),{start:'staged'}),cab={...r};
 for(const slot of [1,manifest.slots.length]){
  const s=manifest.slots[slot-1],template=tpl(slot),{bytes,report}=await C.fillCab(template,manifest,slot,cab,'synth');
  assert.equal(report.filename,C.fileName(slot,'synth'));assert.equal(report.fxid,929+slot);
  const allowed=i=>(i>=s.fir_offset&&i<s.fir_offset+4*32)||(i>=s.sos_offset&&i<s.sos_offset+20*6)||(i>=s.gain_offset&&i<s.gain_offset+4)||(i>=s.name_offset&&i<s.name_offset+12)
   ||(i>=s.picture_offset&&i<s.picture_offset+manifest.cover.capacity);
  for(let i=0;i<template.length;i++)if(!allowed(i))assert.equal(bytes[i],template[i],`slot ${slot} byte ${i} changed`);
  const v=new DataView(bytes.buffer);assert.equal(v.getFloat32(s.fir_offset,true),Math.fround(r.fir[0]));assert.equal(v.getFloat32(s.gain_offset,true),Math.fround(r.gain));
  assert.equal(Buffer.from(bytes.slice(s.name_offset,s.name_offset+12)).toString().replace(/\0/g,''),'CAB-synth');
 }
 const damaged=Buffer.from(tpl(1));damaged[200]^=1;await assert.rejects(C.fillCab(damaged,manifest,1,cab,'x'),/damaged/);
 await assert.rejects(C.fillCab(tpl(1),manifest,2,cab,'x'),/damaged/,'slot 1 bytes as slot 2');
 await assert.rejects(C.fillCab(tpl(1),manifest,1,{...cab,sos:[[1,0,0,-2.1,1.2],...cab.sos.slice(1)]},'x'),/Unstable/);
 await assert.rejects(C.fillCab(tpl(1),manifest,1,{...cab,fir:cab.fir.slice(1)},'x'),/Invalid cab/);
});

test('slots: a cab keeps its slot; removing frees it for the next one',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 const cabs=[{slot:1,name:'a'},{slot:2,name:'b'},{slot:3,name:'c'}];C.saveCabs(storage,cabs);
 const after=C.readCabs(storage).filter(c=>c.slot!==2);assert.equal(C.freeSlot(after,16),2);
 assert.equal(C.freeSlot(Array.from({length:16},(_,i)=>({slot:i+1})),16),0);
});

test('cab pedal names stay within 9 characters and keep the full name for Patch Editor',async()=>{
 const r=C.fit(synthCab(),{start:'staged'}),s=manifest.slots[0];
 const {bytes,report}=await C.fillCab(tpl(1),manifest,1,{...r},'tonehunt');
 assert.equal(report.displayName,'CAB-toneh');assert.equal(report.name,'CabIR-tonehunt');
 assert.equal(bytes[s.name_offset+9],0);
});
