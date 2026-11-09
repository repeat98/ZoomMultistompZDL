const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const S=require('../slot_identity.js'),N=require('../nam_loader.js'),C=require('../cab_loader.js');
const base=path.join(__dirname,'..');
const sha=async b=>crypto.createHash('sha256').update(b).digest('hex');
const engines=[['nam_template','multi.json'],['nam_template_eco','multi.json'],['cab_template','cab.json']]
 .map(([dir,file])=>({dir,man:JSON.parse(fs.readFileSync(path.join(base,dir,file)))}));
// Synthetic A2 Lite capture (as nam_loader.test.cjs); no real capture in the repo.
function model(){return {sample_rate:48000,architecture:'WaveNet',weights:Array.from({length:1871},(_,i)=>i/2000),config:{head:null,layers:[{channels:3,bottleneck:3,input_size:1,condition_size:1,kernel_sizes:[...Array(14).fill(6),15,15,...Array(7).fill(6)],dilations:[1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239],head:{out_channels:1,kernel_size:16,bias:true},layer1x1:{active:true,groups:1},head1x1:{active:false},groups_input:1,groups_input_mixin:1,activation:Array.from({length:23},()=>({type:'LeakyReLU',negative_slope:.01})),gating_mode:Array(23).fill('none')}]}};}
const read=(e,f)=>fs.readFileSync(path.join(base,e.dir,f));

test('rebuilding .hash leaves every shipped slot template byte-identical',()=>{
 for(const e of engines)for(const s of e.man.slots){
  const t=new Uint8Array(read(e,s.file)),before=Buffer.from(t);S.rehash(t);assert.ok(before.equals(Buffer.from(t)),`${e.dir} ${s.file}`);
 }
});

test('generated slots equal the linker-built reference slots byte for byte',async()=>{
 for(const e of engines){
  const g=e.man.generated,b=read(e,g.file);assert.equal(g.first,17);assert.equal(g.last,216);
  for(const [slot,ref] of Object.entries(g.reference_sha256))assert.equal(await sha(await S.generateSlot(b,e.man,Number(slot),sha)),ref,`${e.dir} slot ${slot}`);
  const bad=Buffer.from(b);bad[1000]^=1;await assert.rejects(S.generateSlot(bad,e.man,17,sha),/damaged/);
 }
});

test('slot identities: shipped IDs unchanged, generated ranges distinct and within 10-bit FXIDs',()=>{
 const nam=engines[0].man,cab=engines[2].man,ids=new Set();
 for(let s=1;s<=216;s++){
  const n=S.slotMeta(nam,s),c=S.slotMeta(cab,s);
  assert.equal(n.fxid,N.namFxid(s));assert.equal(c.fxid,C.cabFxid(s));assert.ok(n.fxid<1024&&c.fxid<1024);
  ids.add(n.fxid);ids.add(c.fxid);
 }
 assert.equal(ids.size,432,'no slot shares an FXID');
 assert.equal(N.namFxid(1),900);assert.equal(N.namFxid(16),957);assert.equal(N.namFxid(17),500);assert.equal(N.namFxid(216),699);
 assert.equal(C.cabFxid(1),930);assert.equal(C.cabFxid(16),945);assert.equal(C.cabFxid(17),700);assert.equal(C.cabFxid(216),899);
 assert.throws(()=>S.slotMeta(nam,217));assert.throws(()=>S.slotMeta(nam,0));
});

test('filenames stay within 8 characters and unique across all 216 slots',()=>{
 const nam=new Set(),cab=new Set();
 for(let s=1;s<=216;s++){
  for(const name of ['a','Zz','smokey','tonehunt']){
   const f=N.fileName(s,name),c=C.fileName(s,name);
   assert.ok(f.length-4<=8&&c.length-4<=8,`${f} ${c}`);nam.add(s+':'+f.slice(0,-4).toLowerCase());cab.add(s+':'+c.slice(0,-4).toLowerCase());
  }
 }
 // A file from one slot must never truncate to another slot's name.
 const owner=new Map();
 for(const k of [...nam,...cab].map(x=>x.split(':'))){const [slot,stem]=k;if(owner.has(stem))assert.equal(owner.get(stem),slot,stem);owner.set(stem,slot);}
 assert.throws(()=>C.cabName('0abc'),/starting with a letter/);
});

test('captures and cabs export into generated slots with the right identity',async()=>{
 const nam=engines[0].man,m=model();
 for(const slot of [17,100,216]){
  const r=await N.convertNamed(m,read(engines[0],nam.generated.file),nam,slot,'smokey');
  assert.equal(Buffer.from(r.bytes).readUInt16LE(64),N.namFxid(slot));assert.equal(r.report.fxid,N.namFxid(slot));
  assert.equal(r.report.filename,N.fileName(slot,'smokey'));assert.equal(r.report.displayName,'NAM-smoke');
 }
 const cab=engines[2].man,fit=C.fit((()=>{const x=new Float64Array(600);x[2]=1;return x;})(),{start:'staged'});
 for(const slot of [17,216]){
  const {bytes,report}=await C.fillCab(read(engines[2],cab.generated.file),cab,slot,fit,'sm57');
  assert.equal(Buffer.from(bytes).readUInt16LE(64),C.cabFxid(slot));assert.equal(report.fxid,C.cabFxid(slot));assert.equal(report.filename,C.fileName(slot,'sm57'));
 }
});
