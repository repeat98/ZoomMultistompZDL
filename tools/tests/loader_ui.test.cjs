const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const C=require('../cab_loader.js');
const html=fs.readFileSync(path.join(__dirname,'../nam_loader.html'),'utf8');
function imports(max=16){
 const pending=[],messages=[],el={files:[],value:'',addEventListener(_,fn){this.handler=fn;}};
 const ctx=vm.createContext({CabLoader:C,$:()=>el,cabs:[],busy:0,maxSlots:()=>max,
  clearCabDownloads(){},render(){},persist(){},cabStatus:(s)=>messages.push(s),
  fitInBackground:()=>new Promise((resolve,reject)=>pending.push({resolve,reject}))});
 vm.runInContext(html.slice(html.indexOf("$('irs').addEventListener"),html.indexOf("$('buildCab').addEventListener")),ctx);
 const start=name=>{el.files=[{name,size:1,arrayBuffer:async()=>new ArrayBuffer(1)}];return el.handler();};
 return {ctx,pending,messages,start};
}
test('overlapping cab imports get distinct slots even when fits finish out of order',async()=>{
 const h=imports(),a=h.start('first.wav'),b=h.start('second.wav');
 await new Promise(setImmediate);
 h.pending[1].resolve({errorDb:0});await b;
 h.pending[0].resolve({errorDb:0});await a;
 assert.deepEqual(Array.from(h.ctx.cabs,c=>[c.name,c.slot]),[['second',1],['first',2]]);
 assert.equal(h.ctx.busy,0);
});
test('concurrent import cannot overflow the last free cab slot',async()=>{
 const h=imports(1),a=h.start('first.wav'),b=h.start('second.wav');
 await new Promise(setImmediate);
 h.pending[0].resolve({errorDb:0});await a;
 h.pending[1].resolve({errorDb:0});await b;
 assert.equal(h.ctx.cabs.length,1);assert.equal(h.ctx.cabs[0].slot,1);
 assert.ok(h.messages.some(s=>s.includes('All 1 cab slots are used')));
 assert.equal(h.ctx.busy,0);
});
test('failed cab fits do not consume a slot',async()=>{
 const h=imports(),a=h.start('bad.wav');await new Promise(setImmediate);
 h.pending[0].reject(Error('bad WAV'));await a;
 const b=h.start('good.wav');await new Promise(setImmediate);
 h.pending[1].resolve({errorDb:0});await b;
 assert.equal(h.ctx.cabs[0].slot,1);assert.equal(h.ctx.busy,0);
});
test('legacy cab migration runs once and respects an intentionally empty current bank',()=>{
 const data=new Map([['cabir-bank-v1',JSON.stringify([{name:'oldcab'}])]]);
 const storage={getItem:k=>data.has(k)?data.get(k):null,setItem:(k,v)=>data.set(k,v)};
 const migrate=()=>{const ctx=vm.createContext({CabLoader:C,localStorage:storage,cabs:C.readCabs(storage)});
  vm.runInContext(html.split('\n').find(l=>l.startsWith('try{const old=')),ctx);return ctx.cabs;};
 assert.equal(migrate()[0].name,'oldcab');
 C.saveCabs(storage,[]);assert.equal(migrate().length,0);
 C.saveCabs(storage,[{slot:3,name:'newcab'}]);
 assert.equal(migrate()[0].name,'newcab');assert.equal(migrate()[0].slot,3);
});
