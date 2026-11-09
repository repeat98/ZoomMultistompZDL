const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const src=fs.readFileSync(require('node:path').join(__dirname,'../patch_editor.html'),'utf8');
function fn(name){const start=src.search(new RegExp('(?:async )?function '+name+'\\('));assert(start>=0);return src.slice(start,src.indexOf('\n}',start)+2);}
function context(extra={}){return vm.createContext({setTimeout,clearTimeout,performance,Promise,Map,Set,Math,Array,Number,Error,busy:false,syncing:false,midiActionActive:false,actionCancelled:false,transientBypassSlot:-1,patchGeneration:0,nextSend:0,dumpCooldownUntil:0,pendingDump:null,sxAccum:null,fsWaiter:null,autoApplyPending:false,sleep:async()=>{},banner:()=>{},log:()=>{},updateActionState:()=>{},...extra});}
test('capture sync restores original DSP costs when saved overrides disappear or become invalid',()=>{
 for(const baseline of [194,177]){
  let saved=[{slot:1,shortName:'eco',cost:160}];
  const e={namSlot:1,name:'NAMLite-original',captureName:'original',cost:baseline};
  const c=context({DB:{custom:[e]},localStorage:{getItem:k=>k==='namlite-captures-v1'?JSON.stringify(saved):'[]'}});
  vm.runInContext(['const NAM_BASE_COVERS=','let COVER_BLOCKS=','const NAM_BASE_COSTS='].map(k=>src.split('\n').find(l=>l.startsWith(k))).join('\n')+'\n'+fn('coverB64')+'\n'+fn('syncNamCaptureNames'),c);
  assert.equal(c.syncNamCaptureNames(),true);assert.equal(e.cost,160);
  saved=[];assert.equal(c.syncNamCaptureNames(),true);
  assert.equal(e.cost,baseline);assert.equal(e.name,'NAMLite-original');
  assert.equal(c.syncNamCaptureNames(),false);
  saved=[{slot:1,shortName:'eco',cost:160}];c.syncNamCaptureNames();
  saved=[{slot:1,shortName:'eco',cost:'invalid'}];c.syncNamCaptureNames();
  assert.equal(e.cost,baseline);
 }
});
test('transaction rejects overlap and releases ownership after failure',async()=>{
 const c=context();vm.runInContext(fn('cancelDump')+'\n'+fn('midiAction'),c);
 let finish;let calls=0;
 const first=c.midiAction(()=>new Promise(r=>finish=r))();
 assert.equal(await c.midiAction(()=>calls++)(),false);assert.equal(calls,0);
 finish();await first;assert.equal(c.midiActionActive,false);
 await c.midiAction(()=>{throw Error('failed')})();assert.equal(c.midiActionActive,false);assert.equal(c.busy,false);
});
test('busy timeout never grants access',async()=>{
 let now=0;const c=context({busy:true,performance:{now:()=>now},sleep:async()=>{now+=50;}});
 vm.runInContext(fn('waitIdle'),c);await assert.rejects(c.waitIdle(100),/still busy/);assert.equal(c.busy,true);
});
test('dump registers before sending and refuses competing requests',async()=>{
 const c=context({zx:x=>x,send:()=>{}});vm.runInContext(fn('awaitDump')+'\n'+fn('cancelDump'),c);
 const first=c.awaitDump(1000);await new Promise(setImmediate);const owner=c.pendingDump;
 await assert.rejects(c.awaitDump(1000),/already pending/);assert.equal(c.pendingDump,owner);
 c.cancelDump();assert.equal(await first,null);
 c.send=()=>{const r=c.pendingDump;assert(r);clearTimeout(r.t);c.pendingDump=null;r.res([42]);};
 assert.deepEqual(await c.awaitDump(),[42]);
});
function applyContext(){
 const live={name:'Pedal rename',fx:[[1,42,25,70]]};let sent;
 const c=context({patch:{name:'Old name',fx:[[1,42,60,10]]},midiOut:{},READ_ONLY:false,DEVID:97,
 dirty:new Set(['0,2']),dirtyVersions:new Map([['0,2',1]]),lastEditedSlot:null,
 waitIdle:async()=>{},decodePatch:x=>JSON.parse(JSON.stringify(x)),encodePatch:x=>{sent=structuredClone(x);return sent;},
 zx:x=>x,send:()=>{},render:()=>{},reconcilePatch:p=>{c.patch=p;},readCurrent:async()=>structuredClone(live),lockSiblingWrites:()=>{}});
 vm.runInContext(fn('applyToPedal'),c);return {c,live,getSent:()=>sent};
}
test('Apply preserves live name and untouched fields; clears only verified edits',async()=>{
 const {c,live}=applyContext();let reads=0;
 c.readCurrent=async()=>{if(reads++)live.fx[0][2]=60;const r=structuredClone(live);r.slice=()=>structuredClone(live);return r;};
 await c.applyToPedal();assert.equal(c.patch.name,'Pedal rename');assert.equal(c.patch.fx[0][3],70);assert.equal(c.dirty.size,0);
});
test('failed verification and newer revisions retain edits',async()=>{
 for(const newer of [false,true]){
 const {c,live}=applyContext();let reads=0;
 c.readCurrent=async()=>{if(reads++){if(newer){live.fx[0][2]=60;c.dirtyVersions.set('0,2',2);c.patch.fx[0][2]=61;}}
 const r=structuredClone(live);r.slice=()=>structuredClone(live);return r;};
 await c.applyToPedal();assert(c.dirty.has('0,2'));assert.equal(c.patch.fx[0][2],newer?61:60);
 }
});
test('read failure retains all edits and releases busy state',async()=>{
 const {c}=applyContext();c.readCurrent=async()=>null;
 await assert.rejects(c.applyToPedal(),/read failed/);assert(c.dirty.has('0,2'));assert.equal(c.busy,false);
});
test('obsolete timeout cannot erase a newer dump',async()=>{
 const timers=[];const c=context({setTimeout:f=>{timers.push(f);return timers.length;},clearTimeout:()=>{},zx:x=>x,send:()=>{}});
 vm.runInContext(fn('awaitDump')+'\n'+fn('cancelDump'),c);
 const first=c.awaitDump();await new Promise(setImmediate);c.cancelDump();await first;
 const second=c.awaitDump();await new Promise(setImmediate);const owner=c.pendingDump;
 timers[0]();assert.equal(c.pendingDump,owner);c.cancelDump();await second;
});
test('Apply aborts when pedal changes patch during the initial read',async()=>{
 const {c,live}=applyContext();let writes=0;c.send=()=>writes++;
 c.readCurrent=async()=>{c.patchGeneration++;return live;};
 await assert.rejects(c.applyToPedal(),/patch changed/);assert.equal(writes,0);assert(c.dirty.has('0,2'));
});
test('connect bank dialog reloads only for Yes; No and dismissal do nothing',async()=>{
 for(const answer of ['yes','no',null]){
  let reads=0;const dialog={returnValue:'yes',showModal(){if(answer!==null)this.returnValue=answer;this.onclose();}};
  const c=context({$:()=>dialog,readAll:async()=>{reads++;}});
  vm.runInContext(fn('offerBankReload'),c);await c.offerBankReload();
  assert.equal(reads,answer==='yes'?1:0);
 }
});

test('late-slot knob edits never emit unsupported live messages',()=>{
 const sent=[];let enables=0;const c=context({liveEditable:s=>s<3,editEnable:()=>enables++,zx:x=>x,send:x=>sent.push(x)});
 vm.runInContext(fn('sendParam'),c);
 for(let s=3;s<6;s++)c.sendParam(s,2,42);
 assert.equal(sent.length,0);assert.equal(enables,0);
 c.sendParam(2,2,300);assert.deepEqual(Array.from(sent[0]),[0x31,2,2,44,2]);
});
test('parameter echo updates only its knob, with no render or name mutation',()=>{
 let received;let renders=0;
 const c=context({DEVID:97,patch:{name:'DreamShot',fx:[[1,42,0]]},BYID:{42:{name:'Effect'}},
 KNOBREG:[[{_receive:v=>received=v}]],render:()=>renders++});
 vm.runInContext(fn('handleSysex'),c);
 c.handleSysex([240,82,0,97,49,0,2,63,0,247]);
 assert.equal(c.patch.fx[0][2],63);assert.equal(received,63);assert.equal(renders,0);assert.equal(c.patch.name,'DreamShot');
});
test('all slot parameter edits preserve raw name bytes and collectors',()=>{
 const codec=src.slice(src.indexOf('const BITS='),src.indexOf('function emptyPatch'));
 const c=context();vm.runInContext(codec+";globalThis.base=EMPTY146.slice();globalThis.nameidx=NAMIDX;",c);
 c.base[125]|=64;c.base[133]=85;c.base[141]|=3;
 const original=Array.from(c.nameidx,i=>c.base[i]);
 for(let s=0;s<6;s++)for(let k=2;k<11;k++){
  const p=c.decodePatch(c.base);p.fx[s][k]=73;const raw=c.encodePatch(p,c.base);
  assert.deepEqual(Array.from(c.nameidx,i=>raw[i]),original);
  assert.equal(raw[125]&64,c.base[125]&64);assert.equal(raw[133],85);assert.equal(raw[141]&3,3);
 }
 const p=c.decodePatch(c.base);p.name='New name';const raw=c.encodePatch(p,c.base);
 assert.equal(c.decodePatch(raw).name,'New name');assert.equal(raw[133],0);
});
test('same-topology refresh retains slot arrays and DOM while accepting real renames',()=>{
 let renders=0;let updates=0;const values=[];const old=[1,42,7];
 const c=context({patch:{name:'Old',fx:[old]},KNOBREG:[[{_receive:v=>values.push(v)}]],
 $:()=>({}),updateActionState:()=>updates++,render:()=>renders++});
 vm.runInContext(fn('reconcilePatch'),c);
 c.reconcilePatch({name:'New',fx:[[1,42,9]],dsp:0,curfx:0,maxfx:1});
 assert.equal(c.patch.fx[0],old);assert.equal(old[2],9);assert.equal(c.patch.name,'New');assert.equal(renders,0);assert.equal(updates,1);
 c.reconcilePatch({name:'New',fx:[[1,43,9]]});assert.equal(renders,1);
});
test('tuner controls send original-model CC only and never write patches',()=>{
 const sent=[];const c=context({midiOut:{},READ_ONLY:false,DEVID:97,send:x=>sent.push(Array.from(x))});
 vm.runInContext(fn('setPedalTuner'),c);c.setPedalTuner(true);c.setPedalTuner(false);
 assert.deepEqual(sent,[[176,74,127],[176,74,0]]);
 c.READ_ONLY=true;c.setPedalTuner(true);assert.equal(sent.length,2);
 c.READ_ONLY=false;c.DEVID=110;c.setPedalTuner(true);assert.equal(sent.length,2);
});
test('all slots off preserves live parameters and leaves unrelated local edits pending',async()=>{
 const live={name:'Live name',fx:Array.from({length:6},()=>[1,42,25])};let written,reads=0;
 const copy=x=>JSON.parse(JSON.stringify(x));
 const c=context({patch:copy(live),midiOut:{},READ_ONLY:false,DEVID:97,
 dirty:new Set(['0,2','1,0']),dirtyVersions:new Map(),waitIdle:async()=>{},
 decodePatch:copy,encodePatch:copy,zx:x=>x,send:x=>{if(x.fx)written=copy(x);},
 readCurrent:async()=>{const r=copy(reads++?written:live);r.slice=()=>copy(r);return r;},
 reconcilePatch:p=>{c.patch=p;}});
 c.patch.fx[0][2]=77;vm.runInContext(fn('turnAllSlotsOff'),c);await c.turnAllSlotsOff();
 assert(written.fx.every(f=>f[0]===0));assert.equal(written.fx[0][2],25);
 assert.equal(c.patch.fx[0][2],77);assert(c.dirty.has('0,2'));assert(!c.dirty.has('1,0'));assert.equal(c.busy,false);
});

test('Apply bypass echoes do not alter the model or rebuild slot controls',()=>{
 let rendered=0;
 const c=context({DEVID:97,patch:{fx:[[1,42,25]]},BYID:{42:{name:'test'}},
 transientBypassSlot:0,midiActionActive:true,KNOBREG:[],render:()=>{throw Error("unexpected rebuild");},updateSlotState:()=>rendered++});
 vm.runInContext(fn('handleSysex'),c);
 c.handleSysex([240,82,0,97,49,0,0,0,0,247]);
 assert.equal(c.patch.fx[0][0],1);assert.equal(rendered,0);
 c.transientBypassSlot=-1;c.midiActionActive=false;
 c.handleSysex([240,82,0,97,49,0,0,0,0,247]);
 assert.equal(c.patch.fx[0][0],0);assert.equal(rendered,1);
});

test('slot state changes preserve controls and update only the state display',()=>{
 const classes={};const attrs={};const label={};const hint={};
 const toggle={classList:{toggle:(k,v)=>classes[k]=v},setAttribute:(k,v)=>attrs[k]=v};
 const slot={classList:{toggle:()=>{}},querySelector:q=>({'.toggle':toggle,'.slot-state':label,'.bypassHint':hint}[q])};
 const c=context({patch:{fx:[[0,42]]},$:()=>({children:[slot]})});
 vm.runInContext(fn('updateSlotState'),c);c.updateSlotState(0);
 assert.equal(label.textContent,'Off');assert.equal(attrs['aria-pressed'],'false');assert.equal(hint.hidden,false);
 c.patch.fx[0][0]=1;c.updateSlotState(0);
 assert.equal(label.textContent,'On');assert.equal(attrs['aria-pressed'],'true');assert.equal(hint.hidden,true);
});
test('direct-edit trial enables late-slot messages and suppresses automatic Apply',()=>{
 const sent=[];const c=context({directEditTrial:false,editEnable:()=>{},zx:x=>x,send:x=>sent.push(Array.from(x))});
 vm.runInContext('const LIVE_EDIT_SLOTS=3;const liveEditable=s=>s<LIVE_EDIT_SLOTS||directEditTrial;\n'+fn('sendParam')+'\n'+fn('autoApplyMaybe'),c);
 c.sendParam(3,2,77);assert.equal(sent.length,0);
 c.directEditTrial=true;c.sendParam(3,2,77);assert.deepEqual(sent,[[49,3,2,77,0]]);
 c.setTimeout=()=>{throw Error('trial scheduled Apply');};c.autoApplyMaybe();
});

test('mode selector preserves readback values and sends only on a different detent',()=>{
 const changes=[],releases=[];
 class El {
   constructor(tag){this.tag=tag;this.style={};this.children=[];this.events={};this.attrs={};}
   setAttribute(k,v){this.attrs[k]=v;} appendChild(x){this.children.push(x);} append(...xs){this.children.push(...xs);}
   addEventListener(k,f){this.events[k]=f;} getContext(){return new Proxy({}, {get:()=>()=>{}});}
 }
 let blocked=false;
 const c=context({document:{createElement:t=>new El(t)},window:{devicePixelRatio:1},tok:(k,f)=>f,
 editingBlocked:()=>blocked,autoApplyT:null});
 vm.runInContext(fn('selectorIndex')+'\n'+fn('makeSelector'),c);
 const choices=[{from:0,to:16,value:8,label:'Room'},{from:17,to:33,value:25,label:'Digit'},{from:34,to:100,value:60,label:'Peak'}];
 const w=c.makeSelector('Mode',19,100,v=>changes.push(v),()=>releases.push(1),choices);
 const select=w.children[2];assert.equal(select.value,'1');assert.equal(changes.length,0);
 w._receive(30);assert.equal(select.value,'1');assert.match(select.title,/30/);assert.equal(changes.length,0);
 select.value='1';select.events.change();assert.equal(changes.length,0);
 select.value='2';select.events.change();assert.deepEqual(changes,[60]);assert.equal(releases.length,1);
 blocked=true;select.value='0';select.events.change();assert.equal(select.value,'2');assert.equal(changes.length,1);
 blocked=false;w._setNorm(0);assert.deepEqual(changes,[60,8]);w._release();assert.equal(releases.length,2);
 w._receive(100);assert.equal(select.value,'2');assert.equal(changes.length,2);
});

// MS-50G patch dump from issue #1 (device 0x58, firmware 3.10): "Atomic Gli",
// LineSel / BitCrush / RndmFLTR / PitchDly.
const MS50G_DUMP=('f0 52 00 58 28 0a 10 00 00 04 0c 10 01 00 00 00 00 00 00 00 00 00 00 00 00 00 21 00 00 42 0e 00 '
 +'28 00 1e 00 40 00 06 00 00 00 00 00 00 21 00 01 01 00 04 08 48 44 00 03 20 10 20 45 06 00 00 00 '
 +'00 00 00 01 01 00 00 10 03 78 00 14 30 40 02 40 16 00 '+'00 '.repeat(46)
 +'00 40 11 0f 41 00 74 6f 6d 69 63 20 47 00 6c 69 00 f7').trim().split(/\s+/).map(x=>parseInt(x,16));
function layoutContext(extra={}){
 const c=context(extra);
 const line=k=>src.slice(src.indexOf(k),src.indexOf('\n',src.indexOf(k)));
 const bits=src.slice(src.indexOf('const BITS=['),src.indexOf('\n];',src.indexOf('const BITS=['))+3);
 const db=src.slice(src.indexOf('const DB='),src.indexOf('\n',src.indexOf('const DB=')));
 vm.runInContext(bits+'\n'+line('const NAMIDX=')+'\n'+line('function getBits(')+'\n'+fn('decodePatch')+'\n'+db
  +'\nvar BYID={};for(const e of DB.custom.concat(DB.stock,DB.legacy||[],DB.probes||[]))BYID[e.id]=e;\n'
  +line('const SIBLING_MODELS=')+'\n'+fn('layoutProblems')+'\n'+fn('enableSiblingWrites')+'\n'+fn('lockSiblingWrites')
  +'\nthis.decodePatch=decodePatch;this.layoutProblems=layoutProblems;this.enableSiblingWrites=enableSiblingWrites;this.lockSiblingWrites=lockSiblingWrites;',c);
 return c;
}
test('MS-50G dump decodes with the MS-70CDR layout and every value in range',()=>{
 assert.equal(MS50G_DUMP.length,146);
 const c=layoutContext(),p=c.decodePatch(MS50G_DUMP);
 assert.equal(p.name,'Atomic Gli');assert.equal(p.maxfx,4);
 assert.equal(c.layoutProblems(p).length,0,c.layoutProblems(p).join('; '));
 const bad=MS50G_DUMP.slice();bad[47]=0x7f;bad[45]|=0x20;          // scramble slot 3's id bits
 const q=c.decodePatch(bad);assert.notDeepEqual(q.fx[2][1],p.fx[2][1]);
});
function siblingContext(echo){
 const el={hidden:false},sent=[],notes=[];let reads=0;
 const c=layoutContext({DEVID:0x58,READ_ONLY:true,WRITE_TRIAL:false,midiOut:{},confirm:()=>true,busy:false,busySince:0,lastEnable:0,editModeActive:false,
  $:()=>el,zx:x=>x,hex:a=>Array.from(a,x=>x.toString(16)).join(' '),log:()=>{},banner:m=>notes.push(m),render:()=>{},updateActionState:()=>{},sleep:async()=>{},
  send:b=>{if(c.READ_ONLY&&b[4]===0x28)throw Error('blocked');sent.push(b);},
  readCurrent:async()=>reads++?echo(MS50G_DUMP.slice()):MS50G_DUMP.slice()});
 return {c,el,sent,notes};
}
test('sibling writes unlock only when the unchanged patch reads back byte-identical',async()=>{
 const ok=siblingContext(d=>d);await ok.c.enableSiblingWrites();
 assert.equal(ok.c.READ_ONLY,false);assert.equal(ok.c.WRITE_TRIAL,true);assert.equal(ok.el.hidden,true);
 assert.deepEqual(ok.sent.find(b=>b.length===146),MS50G_DUMP,'the test writes the pedal\'s own bytes back unchanged');
 const off=siblingContext(d=>{d[30]^=1;return d;});await off.c.enableSiblingWrites();
 assert.equal(off.c.READ_ONLY,true);assert.equal(off.c.WRITE_TRIAL,false);assert.match(off.notes.at(-1),/did not pass/);
 const silent=siblingContext(()=>null);await silent.c.enableSiblingWrites();assert.equal(silent.c.READ_ONLY,true);
 const no=siblingContext(d=>d);no.c.confirm=()=>false;await no.c.enableSiblingWrites();assert.equal(no.sent.length,0);assert.equal(no.c.READ_ONLY,true);
 const other=siblingContext(d=>d);other.c.DEVID=0x5b;await other.c.enableSiblingWrites();assert.equal(other.sent.length,0);assert.equal(other.c.READ_ONLY,true);
});
test('a write the sibling pedal does not keep locks writes again; MS-70CDR is unaffected',()=>{
 const s=siblingContext(d=>d);s.c.READ_ONLY=false;s.c.WRITE_TRIAL=true;s.c.lockSiblingWrites('test');
 assert.equal(s.c.READ_ONLY,true);assert.equal(s.c.WRITE_TRIAL,false);
 const m=siblingContext(d=>d);m.c.DEVID=0x61;m.c.READ_ONLY=false;m.c.lockSiblingWrites('test');assert.equal(m.c.READ_ONLY,false);
});

test('capture pictures follow the loader name and icon, and fall back to the DB picture',()=>{
 const A=require('../cover_art.js'),cover=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../nam_template/multi.json'))).cover;
 let saved=[{slot:1,shortName:'smokey',icon:'skull',cost:194}];
 const e={namSlot:1,id:7,name:'NAMLite — capture 1',cost:194,cover:'DBPIC'};
 const c=context({DB:{custom:[e]},CoverArt:A,btoa:s=>Buffer.from(s,'binary').toString('base64'),
  localStorage:{getItem:k=>k==='namlite-captures-v1'?JSON.stringify(saved):'[]'}});
 vm.runInContext(['const NAM_BASE_COVERS=','let COVER_BLOCKS=','const NAM_BASE_COSTS='].map(k=>src.split('\n').find(l=>l.startsWith(k))).join('\n')+'\n'+fn('coverB64')+'\n'+fn('syncNamCaptureNames')+'\nthis.setBlocks=b=>{COVER_BLOCKS=b;};',c);
 c.syncNamCaptureNames();assert.equal(e.cover,'DBPIC','no manifest yet: DB picture');
 c.setBlocks({nam:cover});c.syncNamCaptureNames();
 const px=A.draw(cover,'smokey','skull'),b=Buffer.alloc(1024);px.forEach((v,i)=>{if(v)b[i>>3]|=0x80>>(i&7);});
 assert.equal(e.cover,b.toString('base64'));
 saved=[];c.syncNamCaptureNames();assert.equal(e.cover,'DBPIC','record gone: DB picture back');
});

test('an older build under a retired effect ID can be removed, but is never replaced in place',async()=>{
 const DB={legacy:[{name:'Spool (old 409)',gid:8,fxid:409}]},fsIndex=[{file:'Spool.ZDL',name:'Spool',gid:8,fxid:914}];
 const old={name:'SPOOL.ZDL',size:20746,info:{gid:8,fxid:409,version:'1.01'}};
 const c=context({DB,fsIndex,fsFiles:{files:[old]},fsCanWrite:()=>{},fsInfo:()=>({gid:8,fxid:914,version:'1.02'})});
 vm.runInContext(src.split('\n').find(l=>l.startsWith('const fsRetired='))+'\n'+fn('fsOurs')+'\n'+fn('fsInstall'),c);
 assert.equal(c.fsOurs('SPOOL.ZDL',old.info),true,'the old build is ours to remove');
 assert.equal(c.fsOurs('SPOOL.ZDL',{gid:8,fxid:410}),false,'any other ID is not');
 await assert.rejects(c.fsInstall('Spool.ZDL',[]),/older build under effect ID 8\/409.*Remove it and power-cycle/);
});

test('a slot swap leaves MIDISTOMP routing (byte 17 of each slot block) with the slot position',()=>{
 // Byte 17 of each 18-byte slot block in the decoded patch: bits 0-1 the slot's bus, bits 2-6 mixer settings of
 // that position, bit 7 zero. Raw bytes below hold its low 7 bits; the editor models none of them, so encodePatch
 // keeps them from the pedal's dump while the effects move.
 const c=context();
 vm.runInContext(['const BITS=','const NAMIDX=','const NZBITS=','for(const slot of BITS)','  if(bf[2]===','const EMPTY146='].map(k=>{const at=src.indexOf('\n'+k)+1;return src.slice(at,k==='const BITS='||k==='const EMPTY146='?src.indexOf('];',at)+2:src.indexOf('\n',at));}).join('\n')
  +'\n'+['getBits','setBits','decodePatch','encodePatch','swapNZBits'].map(fn).join('\n')+'\nthis.api={decodePatch,encodePatch,swapNZBits};',c);
 const {decodePatch,encodePatch,swapNZBits}=c.api;
 const base=Array.from({length:146},(_,i)=>i<5||i===145?[0xf0,0x52,0,0x61,0x28][i]??0xf7:(i*37+11)&0x7f);
 const routing=[25,46,66,87,107,128];
 for(const [a,b] of [[0,1],[2,5],[3,4]]){
  const p=decodePatch(base),t=p.fx[a];p.fx[a]=p.fx[b];p.fx[b]=t;
  const out=encodePatch(p,swapNZBits(base,a,b));
  assert.deepEqual(routing.map(i=>out[i]),routing.map(i=>base[i]),'swap '+(a+1)+'/'+(b+1));
  assert.deepEqual(decodePatch(out).fx[a],decodePatch(base).fx[b],'the effect itself moved');
 }
});

test('the whole editor script compiles (no duplicate top-level names)',()=>{
 const scripts=[...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
 assert.ok(scripts.length>0);
 for(const code of scripts)assert.doesNotThrow(()=>new vm.Script(code));
});
