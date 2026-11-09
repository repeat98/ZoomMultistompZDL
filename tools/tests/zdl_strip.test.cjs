const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),{execFileSync}=require('node:child_process');
const {strip}=require('../zdl_strip.js');
const dist=path.join(__dirname,'..','..','dist');
const zdls=fs.readdirSync(dist).filter(f=>/\.zdl$/i.test(f)).map(f=>[f,fs.readFileSync(path.join(dist,f))]);
const STRIP6X=process.env.STRIP6X||'/Applications/ti/ti-cgt-c6000_8.5.0.LTS/bin/strip6x';

// The bytes the pedal loads: every PT_LOAD segment's file range.
function loaded(zdl){
 const e=zdl.subarray(0x4C),v=new DataView(e.buffer,e.byteOffset,e.byteLength),out=[];
 const phoff=v.getUint32(0x1C,true),n=v.getUint16(0x2C,true);
 for(let k=0;k<n;k++){const o=phoff+k*32;if(v.getUint32(o,true)===1){const at=v.getUint32(o+4,true);out.push(Buffer.from(e.subarray(at,at+v.getUint32(o+16,true))));}}
 return out;
}

test('stripping keeps what the pedal loads, and a stripped file strips to itself',()=>{
 for(const [f,b] of zdls){
  const s=strip(b);
  assert.deepEqual(loaded(Buffer.from(s)),loaded(b),f+': loaded segments');
  assert.deepEqual(Buffer.from(strip(s)),Buffer.from(s),f+': strip twice');
  assert.equal(new DataView(s.buffer).getUint32(0x10,true),s.length-0x4C,f+': ZDL size field');
 }
});

test('byte-identical to strip6x on dist/ (when TI\'s toolchain is installed)',{skip:!fs.existsSync(STRIP6X)&&'strip6x not found; set STRIP6X'},()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'zdlstrip-'));
 try{
  for(const [f,b] of zdls){
   const src=path.join(dir,'in.elf'),dst=path.join(dir,'out.elf');
   fs.writeFileSync(src,b.subarray(0x4C));fs.rmSync(dst,{force:true});
   execFileSync(STRIP6X,['-o='+dst,src]);
   assert.deepEqual(Buffer.from(strip(b)).subarray(0x4C),fs.readFileSync(dst),f);
  }
 }finally{fs.rmSync(dir,{recursive:true,force:true});}
});
