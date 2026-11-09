// Slot identities for NAM and CabIR files, shared by both loaders.
//
// Slots 1-16 ship as one linked template each. Slots 17..216 are made here
// from one base template per engine (tools/nam_prototype/
// package_generated_slots.py): linked slots differ only in the FXID in the
// ZDL header, the three slot digits in the effect's name (which also names
// its exported symbols), and the ELF .hash table those names hash into. This
// writes the first two and rebuilds .hash exactly as build/linker.py does.
// The manifest's reference_sha256 holds linker-built slots; the tests require
// this code to reproduce them byte for byte.
(function(root){
'use strict';
function need(ok,msg){if(!ok)throw Error(msg);}
function patchId(fxid){return (((fxid&63)<<17)|(((fxid>>6)&1)<<30)|(((fxid>>7)&7)<<8)|(8<<1))>>>0;}
// SysV ELF hash, as build/linker.py _elf_hash.
function elfHash(bytes){let h=0;for(const c of bytes){h=((h<<4)+c)>>>0;const g=h&0xF0000000;if(g)h^=g>>>24;h=(h&~g)>>>0;}return h;}
function elfStart(b){for(let i=0;i+4<=b.length;i++)if(b[i]===0x7F&&b[i+1]===0x45&&b[i+2]===0x4C&&b[i+3]===0x46)return i;return -1;}
// Rebuild .hash from .dynsym/.dynstr in place. Same bucket count and order as
// the linker: buckets[h % n] chains newest-first over symbols 1..n-1.
function rehash(bytes){
 const e=elfStart(bytes);need(e>=0,'No ELF image in the template.');
 const v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 const shoff=v.getUint32(e+0x20,true),shentsize=v.getUint16(e+0x2E,true),shnum=v.getUint16(e+0x30,true);
 const sec=i=>{const o=e+shoff+i*shentsize;return {type:v.getUint32(o+4,true),offset:v.getUint32(o+16,true),size:v.getUint32(o+20,true),link:v.getUint32(o+24,true)};};
 let hash=null;for(let i=0;i<shnum;i++){const s=sec(i);if(s.type===5){hash=s;break;}}
 need(hash,'No .hash section in the template.');
 const sym=sec(hash.link),str=sec(sym.link),H=e+hash.offset;
 const nb=v.getUint32(H,true),nc=v.getUint32(H+4,true);
 need(nc===sym.size/16&&8+4*(nb+nc)===hash.size,'Unexpected .hash layout.');
 const buckets=new Uint32Array(nb),chains=new Uint32Array(nc);
 for(let i=1;i<nc;i++){
  const nameAt=e+str.offset+v.getUint32(e+sym.offset+16*i,true);let end=nameAt;while(bytes[end])end++;
  const h=elfHash(bytes.subarray(nameAt,end))%nb;chains[i]=buckets[h];buckets[h]=i;
 }
 buckets.forEach((x,i)=>v.setUint32(H+8+4*i,x,true));chains.forEach((x,i)=>v.setUint32(H+8+4*(nb+i),x,true));
 return bytes;
}
function generated(manifest){return manifest&&manifest.generated||null;}
function slotCount(manifest){const g=generated(manifest);return g?g.last:manifest.slots.length;}
// Everything a loader needs about a slot: from the manifest for 1-16, computed
// for generated slots ('file' is then the shared base template).
function slotMeta(manifest,slot){
 const listed=manifest.slots.find(s=>s.slot===slot);if(listed)return {...listed,generated:false};
 const g=generated(manifest);need(g&&Number.isInteger(slot)&&slot>=g.first&&slot<=g.last,'No such slot.');
 const fxid=g.fxid_offset+slot,{reference_sha256,ident_offsets,...rest}=g;
 return {...rest,slot,fxid,id:patchId(fxid),generated:true};
}
// Slot bytes from the base template; checks the base first.
async function generateSlot(base,manifest,slot,sha256){
 const g=generated(manifest),meta=slotMeta(manifest,slot);need(meta.generated,'Slot '+slot+' has its own template.');
 const b=new Uint8Array(base);need(b.length===g.bytes&&await sha256(b)===g.sha256,'The slot base template is damaged or outdated. Reload the page.');
 const out=b.slice(),digits=String(slot).padStart(g.ident_digits,'0');need(digits.length===g.ident_digits,'Slot number too large.');
 new DataView(out.buffer).setUint16(64,meta.fxid,true);
 for(const at of g.ident_offsets)for(let k=0;k<digits.length;k++)out[at+k]=digits.charCodeAt(k);
 return rehash(out);
}
const api={patchId,elfHash,rehash,slotCount,slotMeta,generateSlot};
if(typeof module!=='undefined')module.exports=api;else root.SlotIdentity=api;
})(globalThis);
