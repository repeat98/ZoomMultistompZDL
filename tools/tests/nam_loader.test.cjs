const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const api=require('../nam_loader.js');
const base=path.join(__dirname,'..');
const engine=fs.readFileSync(path.join(base,'nam_template/engine.bin'));
const manifest=JSON.parse(fs.readFileSync(path.join(base,'nam_template/manifest.json')));
function model(){return {sample_rate:48000,architecture:'WaveNet',weights:Array.from({length:1871},(_,i)=>i/2000),config:{head:null,layers:[{channels:3,bottleneck:3,input_size:1,condition_size:1,kernel_sizes:[...Array(14).fill(6),15,15,...Array(7).fill(6)],dilations:[1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239],head:{out_channels:1,kernel_size:16,bias:true},layer1x1:{active:true,groups:1},head1x1:{active:false},groups_input:1,groups_input_mixin:1,activation:Array.from({length:23},()=>({type:'LeakyReLU',negative_slope:.01})),gating_mode:Array(23).fill('none')}]}};}
test('only weights and version can change; no mutation of input template',async()=>{
 const original=Buffer.from(engine),m=model(),r=await api.convert(m,engine,manifest);
 assert.deepEqual(engine,original);assert.equal(r.bytes.length,engine.length);
 const allowed=i=>(i>=manifest.weights_offset&&i<manifest.weights_offset+1871*4)||(i>=68&&i<76);
 for(let i=0;i<engine.length;i++)if(!allowed(i))assert.equal(r.bytes[i],engine[i],String(i));
 const v=new DataView(r.bytes.buffer);assert.equal(v.getFloat32(manifest.weights_offset+3*4,true),Math.fround(m.weights[3]));
 assert.equal(v.getFloat32(manifest.weights_offset+4*4,true),Math.fround(m.weights[3+6]));
 assert.equal(v.getFloat32(manifest.weights_offset+12*4,true),Math.fround(m.weights[4]));
 assert.equal(Buffer.from(r.bytes.slice(68,72)).toString(),'0.13');
});
test('finds compatible Lite submodel even when it is not first',()=>{
 const large=model();large.config.layers[0].channels=8;
 const root={sample_rate:48000,architecture:'SlimmableContainer',config:{submodels:[{model:large},{model:model()}]}};
 assert.equal(api.selectModel(root).submodel,1);
});
test('rejects malformed and unsupported captures before producing bytes',async()=>{
 for(const modify of [m=>m.sample_rate=96000,m=>m.architecture='LSTM',m=>m.weights.pop(),m=>m.weights[0]=NaN,m=>m.weights[0]=1e100,m=>m.weights[0]='1',m=>m.config.layers[0].channels=8,m=>m.config.layers[0].dilations[0]=2,m=>m.config.layers[0].activation[0].type='Tanh',m=>m.config.layers[0].conv_pre_film={active:true},m=>m.config.layers[0].gating_mode[0]='gated',m=>m.config.layers[0].secondary_activation=['Tanh']]){
  const m=model();modify(m);await assert.rejects(api.convert(m,engine,manifest));
 }
});
test('rejects corrupt template and offsets',async()=>{
 const corrupt=Buffer.from(engine);corrupt[100]^=1;
 await assert.rejects(api.convert(model(),corrupt,manifest),/damaged/);
 await assert.rejects(api.convert(model(),engine,{...manifest,weights_offset:engine.length}),/offsets/);
});
const multi=JSON.parse(fs.readFileSync(path.join(base,'nam_template/multi.json')));
test('eight distinct named exports preserve DSP, linkage and original NAM identity',async()=>{
 const identities=new Set(),filenames=new Set();
 for(const slot of multi.slots){
  const engine=fs.readFileSync(path.join(base,'nam_template',slot.file));
  const r=await api.convertNamed(model(),engine,multi,slot.slot,'smokey');
  assert.equal(r.report.filename,'NAM'+slot.slot+(slot.slot<10?'smok':'smo')+'.ZDL');filenames.add(r.report.filename);assert.equal(r.report.displayName,'NAM-smoke');
  assert.equal(Buffer.from(r.bytes).readUInt16LE(64),api.namFxid(slot.slot));assert.equal(slot.fxid,slot.slot<=8?899+slot.slot:941+slot.slot);
  assert.notEqual(r.report.fxid,498);identities.add(r.report.id);
  const end=r.bytes.slice(slot.name_offset,slot.name_offset+12);
  assert.equal(Buffer.from(end).toString().replace(/\0/g,''),'NAM-smoke');
  const allowed=i=>(i>=slot.weights_offset&&i<slot.weights_offset+1871*4)||(i>=68&&i<76)||(i>=slot.name_offset&&i<slot.name_offset+12)
   ||(i>=slot.picture_offset&&i<slot.picture_offset+multi.cover.capacity);
  for(let i=0;i<engine.length;i++)if(!allowed(i))assert.equal(r.bytes[i],engine[i]);
 }
 assert.equal(identities.size,16);assert.equal(multi.slots.length,16);
 // The pedal truncates basenames to 8 chars; equal truncated names freeze it on boot.
 assert.equal(new Set([...filenames].map(f=>f.replace(/\.ZDL$/,'').slice(0,8).toLowerCase())).size,16);
 for(const f of filenames)assert.ok(f.replace(/\.ZDL$/,'').length<=8,f);
});
test('capture filenames stay within 8 characters for every legal name',()=>{
 for(const name of ['a','smokey','abcdefgh','Z-9_'])for(let slot=1;slot<=16;slot++){
  const f=api.fileName(slot,name);assert.match(f,/^NAM([1-9]|1[0-6])[A-Za-z0-9_-]{1,4}\.ZDL$/);assert.ok(f.length-4<=8);
 }
 // Two installed captures must never share a (case-folded) basename: one name
 // per slot, every combination of slots, including slot 1 vs 10-16.
 const names=['ab','abcdefgh','b0c','zz-9'],seen=new Map();
 for(let slot=1;slot<=16;slot++)for(const n of names){const k=api.fileName(slot,n).toLowerCase();
  if(seen.has(k))assert.equal(seen.get(k),slot,`${k}: slots ${seen.get(k)} and ${slot} collide`);seen.set(k,slot);}
});
test('invalid names and unreserved slots cannot export',async()=>{
 const engine=fs.readFileSync(path.join(base,'nam_template',multi.slots[0].file));
 for(const name of ['','123456789','../evil','<script>','test name','сло','0abc'])await assert.rejects(api.convertNamed(model(),engine,multi,1,name));
 await assert.rejects(api.convertNamed(model(),engine,multi,17,'smokey'));
 await assert.rejects(api.convertNamed(model(),engine,multi,2,'smokey'),'slot 1 template used as slot 2');
});
test('registry retains other slots and prevents duplicate filenames',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 api.remember(storage,{slot:1,shortName:'smokey'});api.remember(storage,{slot:2,shortName:'mega'});
 api.remember(storage,{slot:1,shortName:'fuzz'});
 assert.equal(api.readRegistry(storage).find(e=>e.slot===2).shortName,'mega');
 assert.throws(()=>api.remember(storage,{slot:3,shortName:'MEGA'}));
 assert.equal(api.readRegistry(storage).length,2);
});

test('pedal names fit the pedal screen: at most 9 characters, NUL-terminated, unique on the pedal',async()=>{
 const slot=multi.slots[0],engine=fs.readFileSync(path.join(base,'nam_template',slot.file));
 for(const name of ['a','smoke44','tonehunt','Z-9_abcd']){
  const r=await api.convertNamed(model(),engine,multi,slot.slot,name),field=Buffer.from(r.bytes.slice(slot.name_offset,slot.name_offset+12));
  assert.ok(r.report.displayName.length<=9,r.report.displayName);assert.equal(field[r.report.displayName.length],0,'terminated');
  assert.equal(r.report.name,'NAMLite-'+name,'Patch Editor keeps the full name');
 }
 const data=new Map(),storage={getItem:k=>data.get(k),setItem:(k,v)=>data.set(k,v)};
 api.remember(storage,{slot:1,shortName:'smoke44'});
 assert.throws(()=>api.remember(storage,{slot:2,shortName:'smokeco'}),/already shows as NAM-smoke/);
 api.remember(storage,{slot:2,shortName:'smoky'});api.remember(storage,{slot:1,shortName:'smoke45'});
});
test('Eco+ slots get the correction filter written, and refuse to export without it',async()=>{
 const eco=JSON.parse(fs.readFileSync(path.join(base,'nam_template_ecoplus/multi.json')));
 assert.equal(eco.eco_plus,true);assert.equal(eco.eco_steps,4);
 const ids=require('../slot_identity.js');
 for(const slot of [3,17,216]){
  const meta=ids.slotMeta(eco,slot),tpl=fs.readFileSync(path.join(base,'nam_template_ecoplus',meta.file));
  assert.ok(Number.isInteger(meta.eco_eq_offset));
  await assert.rejects(api.convertNamed(model(),tpl,eco,slot,'smokey'),/correction/);
  const c=Array.from({length:15},(_,i)=>(i+1)/16);
  const r=await api.convertNamed(model(),tpl,eco,slot,'smokey',null,{ecoEq:c});
  const v=new DataView(r.bytes.buffer,r.bytes.byteOffset);
  c.forEach((x,i)=>assert.equal(v.getFloat32(meta.eco_eq_offset+4*i,true),Math.fround(x)));
  assert.equal(v.getFloat32(meta.eco_eq_offset+60,true),Math.fround(16180.339));   // the marker stays
 }
});
test('split slots get the side factors written, keep the marker, and refuse to export without a side',async()=>{
 const sp=JSON.parse(fs.readFileSync(path.join(base,'nam_template_split/multi.json')));
 assert.equal(sp.split,true);assert.equal(sp.eco,false);
 const ids=require('../slot_identity.js');
 for(const slot of [3,17,216]){
  const meta=ids.slotMeta(sp,slot),tpl=fs.readFileSync(path.join(base,'nam_template_split',meta.file));
  assert.ok(Number.isInteger(meta.split_route_offset));
  await assert.rejects(api.convertNamed(model(),tpl,sp,slot,'smokey'),/output gets the amp/);
  await assert.rejects(api.convertNamed(model(),tpl,sp,slot,'smokey',null,{split:3}),/output gets the amp/);
  for(const [route,l,r] of [[1,1,0],[2,0,1]]){
   const out=await api.convertNamed(model(),tpl,sp,slot,'smokey',null,{split:route});
   const v=new DataView(out.bytes.buffer,out.bytes.byteOffset),at=meta.split_route_offset;
   assert.deepEqual([v.getFloat32(at,true),v.getFloat32(at+4,true)],[l,r]);           // amp share of L, R
   assert.equal(v.getFloat32(at+12,true),Math.fround(27182.818));                     // the marker stays
  }
 }
});
