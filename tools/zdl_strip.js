// Strip a Zoom stock ZDL the way Effect Manager installs it, for the browser,
// where TI's strip6x (tools/zoom_fs.py stock --strip) can't run. It drops the
// ELF's .debug_* sections, their section symbols and their names, then lays the
// file out again as strip6x does: sorted relocations, a rebuilt .hash, the
// non-loading sections packed after the loading ones. The code and data the
// pedal loads are untouched.
//
// Byte-identical to strip6x on all 137 effects in the MS-70CDR 2.10 updater
// and on this project's dist/ effects; tools/tests/zdl_strip.test.cjs checks
// the dist/ ones whenever strip6x is installed.
(function(root){
'use strict';
const ZDL_HEADER=0x4C;   // bytes before the ELF; the size field at 0x10 is the ELF's length
const SHT_SYMTAB=2,SHT_STRTAB=3,SHT_HASH=5,SHT_DYNAMIC=6,SHT_NOBITS=8,SHT_DYNSYM=11;
const SHN_LORESERVE=0xff00,STT_SECTION=3,SHF_ALLOC=2;
// .dynamic entries that hold a file offset, and the section type each points at:
// DT_HASH, DT_STRTAB, DT_SYMTAB, DT_RELA, DT_JMPREL.
const DT_OFFSETS=new Map([[4,[SHT_HASH]],[5,[SHT_STRTAB]],[6,[SHT_DYNSYM]],[7,[4]],[0x17,[4,9]]]);
const PT_DYNAMIC=2;

const view=a=>new DataView(a.buffer,a.byteOffset,a.byteLength);
const isPrime=n=>{if(n<2)return false;for(let d=2;d*d<=n;d++)if(n%d===0)return false;return true;};
// The SysV ELF hash of the name at `at` in a string table.
function elfHash(tab,at){let h=0;for(let i=at;tab[i];i++){h=((h<<4)+tab[i])>>>0;const g=h&0xf0000000;if(g)h^=g>>>24;h=(h&~g)>>>0;}return h;}
function cstr(b,at){let e=at;while(b[e])e++;return String.fromCharCode(...b.subarray(at,e));}

// Keep the strings that `used` offsets point into (a name may be a suffix of a
// longer one); return the new table and a map from old offset to new.
function packStrings(tab,used){
  const keep=new Uint8Array(tab.length);keep[0]=1;
  for(const o of used){let e=o;while(e<tab.length&&tab[e]){keep[e]=1;e++;}if(e<tab.length)keep[e]=1;}
  const out=[],at=new Map();let s=0;
  while(s<tab.length){let e=s;while(e<tab.length&&tab[e])e++;
    let any=false;for(let i=s;i<=e&&i<tab.length;i++)if(keep[i]){any=true;break;}
    if(any||s===0){for(let i=s;i<=e&&i<tab.length;i++){at.set(i,out.length);out.push(tab[i]);}}
    s=e+1;}
  return {data:Uint8Array.from(out),map:o=>{const v=at.get(o);if(v===undefined)throw new Error("string offset "+o+" was dropped");return v;}};
}

function strip(zdl){
  zdl=new Uint8Array(zdl);   // a plain copy: slices below are copies, even from a Node Buffer
  const elf=zdl.subarray(ZDL_HEADER);
  if(elf[0]!==0x7f||elf[1]!==0x45||elf[2]!==0x4c||elf[3]!==0x46)throw new Error("not a ZDL");
  const v=view(elf);
  const u16=o=>v.getUint16(o,true),u32=o=>v.getUint32(o,true);
  const phoff=u32(0x1C),shoff=u32(0x20),phentsize=u16(0x2A),phnum=u16(0x2C),shentsize=u16(0x2E),shnum=u16(0x30),shstrndx=u16(0x32);
  const sh=[];for(let i=0;i<shnum;i++){const o=shoff+i*shentsize;sh.push({name:u32(o),type:u32(o+4),flags:u32(o+8),addr:u32(o+12),offset:u32(o+16),size:u32(o+20),link:u32(o+24),info:u32(o+28),align:u32(o+32),entsize:u32(o+36)});}
  const shstr=elf.subarray(sh[shstrndx].offset,sh[shstrndx].offset+sh[shstrndx].size);
  for(const s of sh)s.label=cstr(shstr,s.name);
  const drop=new Set(sh.map((s,i)=>s.label.startsWith(".debug_")?i:-1).filter(i=>i>0));
  const idx=[];let n=0;for(let i=0;i<shnum;i++)idx.push(drop.has(i)?-1:n++);
  const remap=x=>(x>0&&x<SHN_LORESERVE&&x<shnum)?(idx[x]<0?(()=>{throw new Error("reference to a dropped section")})():idx[x]):x;
  const data=sh.map(s=>s.type===SHT_NOBITS?new Uint8Array(0):elf.slice(s.offset,s.offset+s.size));

  // Symbol tables: drop .symtab entries in dropped sections, renumber section indices.
  const strtabUsed=new Map();
  sh.forEach((s,i)=>{
    if(drop.has(i)||(s.type!==SHT_SYMTAB&&s.type!==SHT_DYNSYM))return;
    const d=data[i],dv=view(d),kept=[];let locals=0;
    for(let k=0;k<d.length/16;k++){
      const ent=d.slice(k*16,k*16+16),ev=view(ent),shn=ev.getUint16(14,true);
      if(shn>0&&shn<SHN_LORESERVE&&drop.has(shn)){
        if(s.type===SHT_DYNSYM)throw new Error("a dynamic symbol names a debug section");
        if((ent[12]&15)===STT_SECTION)continue;   // a dropped section's own symbol goes
        ev.setUint16(14,0,true);                  // others stay, with no section (as strip6x leaves them)
      }else ev.setUint16(14,remap(shn),true);
      if(k<s.info)locals++;
      kept.push(ent);
    }
    const out=new Uint8Array(kept.length*16);kept.forEach((e,k)=>out.set(e,k*16));data[i]=out;
    if(s.type===SHT_SYMTAB)s.info=locals;
    const used=strtabUsed.get(s.link)||[];for(let k=0;k<kept.length;k++)used.push(view(kept[k]).getUint32(0,true));strtabUsed.set(s.link,used);
  });
  // String tables the symbols use, then the section-name table.
  for(const [t,used] of strtabUsed){
    if(sh[t].type!==SHT_STRTAB||t===shstrndx)continue;
    if(sh.some((s,i)=>!drop.has(i)&&i!==t&&s.link===t&&s.type!==SHT_SYMTAB))continue;   // shared with something else: leave it whole
    const p=packStrings(data[t],used);data[t]=p.data;
    sh.forEach((s,i)=>{if(drop.has(i)||s.type!==SHT_SYMTAB||s.link!==t)return;const dv=view(data[i]);for(let o=0;o<data[i].length;o+=16)dv.setUint32(o,p.map(dv.getUint32(o,true)),true);});
  }
  const names=packStrings(data[shstrndx],sh.filter((s,i)=>!drop.has(i)).map(s=>s.name));
  data[shstrndx]=names.data;
  sh.forEach((s,i)=>{if(!drop.has(i))s.name=names.map(s.name);});

  // Relocations: strip6x sorts each table by address (a stable sort).
  sh.forEach((s,i)=>{
    if(drop.has(i)||(s.type!==4&&s.type!==9)||!s.entsize)return;
    const e=s.entsize,d=data[i],rows=[];for(let o=0;o+e<=d.length;o+=e)rows.push(d.slice(o,o+e));
    rows.sort((a,b)=>view(a).getUint32(0,true)-view(b).getUint32(0,true));
    rows.forEach((r,k)=>d.set(r,k*e));
  });

  // .hash: strip6x rebuilds it from .dynsym: as many buckets as the smallest
  // prime at or above the symbol count, symbols inserted last to first.
  sh.forEach((s,i)=>{
    if(drop.has(i)||s.type!==SHT_HASH||sh[s.link].type!==SHT_DYNSYM)return;
    const sym=data[s.link],str=data[sh[s.link].link],n=sym.length/16;
    let nb=n;while(!isPrime(nb))nb++;
    data[i]=new Uint8Array((2+nb+n)*4);const hv=view(data[i]);hv.setUint32(0,nb,true);
    const bucket=new Uint32Array(nb),chain=new Uint32Array(n);
    for(let k=n-1;k>0;k--){const h=elfHash(str,view(sym).getUint32(k*16,true))%nb;chain[k]=bucket[h];bucket[h]=k;}
    hv.setUint32(4,n,true);bucket.forEach((x,k)=>hv.setUint32(8+k*4,x,true));chain.forEach((x,k)=>hv.setUint32(8+(nb+k)*4,x,true));
  });

  // Layout, as strip6x does it: the sections that load (SHF_ALLOC) stay where
  // the program headers put them. After the last of them come .dynamic, then
  // the other sections in section-table order, then the program headers, then
  // the section headers.
  const oldOffset=sh.map(s=>s.offset);
  const live=sh.map((s,i)=>i).filter(i=>i>0&&!drop.has(i)&&sh[i].type!==SHT_NOBITS);
  const fixed=live.filter(i=>sh[i].flags&SHF_ALLOC);
  // (An empty section at offset 0 stays there.)
  const loose=live.filter(i=>(sh[i].size||sh[i].offset)&&!(sh[i].flags&SHF_ALLOC)).sort((a,b)=>(sh[b].type===SHT_DYNAMIC)-(sh[a].type===SHT_DYNAMIC)||a-b);
  const base=Math.max(u16(0x28),...fixed.map(i=>sh[i].offset+sh[i].size));
  if(loose.some(i=>sh[i].size&&sh[i].offset<base))throw new Error("a non-loading section sits among the loading ones; not stripping");
  let at=base;
  const alignOf=s=>Math.max(s.align||1,(s.type===SHT_SYMTAB||s.type===SHT_DYNSYM||s.type===SHT_HASH)?4:1);
  for(const i of loose){const a=alignOf(sh[i]);at=Math.ceil(at/a)*a;sh[i].offset=at;sh[i].size=data[i].length;at+=data[i].length;}
  for(const s of sh)if(s.type===SHT_HASH&&!s.entsize)s.entsize=4;
  const newPhoff=Math.ceil(at/4)*4,newShoff=newPhoff+phnum*phentsize;
  const kept=sh.filter((s,i)=>!drop.has(i));
  const out=new Uint8Array(newShoff+kept.length*shentsize);
  out.set(elf.subarray(0,base));
  for(const i of loose)out.set(data[i],sh[i].offset);
  out.set(elf.subarray(phoff,phoff+phnum*phentsize),newPhoff);
  // Where a section of `types` that started at file offset `old` is now.
  const movedTo=(old,types)=>{const i=loose.find(i=>oldOffset[i]===old&&types.includes(sh[i].type));return i===undefined?old:sh[i].offset;};
  const ov=view(out);
  // Program headers (PT_DYNAMIC) and .dynamic hold file offsets of sections that moved.
  for(let k=0;k<phnum;k++){const o=newPhoff+k*phentsize;if(ov.getUint32(o,true)===PT_DYNAMIC)ov.setUint32(o+4,movedTo(ov.getUint32(o+4,true),[SHT_DYNAMIC]),true);}
  sh.forEach((s,i)=>{if(drop.has(i)||s.type!==SHT_DYNAMIC)return;
    for(let o=s.offset;o+8<=s.offset+s.size;o+=8){const tag=ov.getUint32(o,true),val=ov.getUint32(o+4,true);if(DT_OFFSETS.has(tag))ov.setUint32(o+4,movedTo(val,DT_OFFSETS.get(tag)),true);}});
  kept.forEach((s,k)=>{const o=newShoff+k*shentsize;
    const link=(s.type===SHT_SYMTAB||s.type===SHT_DYNSYM||s.link)?remap(s.link):s.link;
    const info=(s.type===4||s.type===9)&&s.info?remap(s.info):s.info;   // REL/RELA name the section they apply to
    [s.name,s.type,s.flags,s.addr,s.offset,s.size,link,info,s.align,s.entsize].forEach((x,j)=>ov.setUint32(o+j*4,x,true));});
  ov.setUint32(0x1C,newPhoff,true);ov.setUint32(0x20,newShoff,true);ov.setUint16(0x30,kept.length,true);ov.setUint16(0x32,idx[shstrndx],true);
  const res=new Uint8Array(ZDL_HEADER+out.length);res.set(zdl.subarray(0,ZDL_HEADER));res.set(out,ZDL_HEADER);
  view(res).setUint32(0x10,out.length,true);
  return res;
}

// ---- Zoom's effects from Zoom's own firmware updater (as zoom_fs.py stock) ----

// One file from a zip, found by `want(name)`; stored or deflated entries.
async function unzipOne(bytes,want){
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes),v=view(b),dec=new TextDecoder();
  let end=b.length-22;while(end>=0&&v.getUint32(end,true)!==0x06054b50)end--;
  if(end<0)throw new Error("not a zip file");
  let at=v.getUint32(end+16,true);
  for(let k=v.getUint16(end+10,true);k>0;k--){
    if(v.getUint32(at,true)!==0x02014b50)throw new Error("the zip's directory is damaged");
    const method=v.getUint16(at+10,true),csize=v.getUint32(at+20,true),size=v.getUint32(at+24,true),off=v.getUint32(at+42,true);
    const nl=v.getUint16(at+28,true),name=dec.decode(b.subarray(at+46,at+46+nl));
    at+=46+nl+v.getUint16(at+30,true)+v.getUint16(at+32,true);
    if(!want(name))continue;
    const start=off+30+v.getUint16(off+26,true)+v.getUint16(off+28,true),raw=b.subarray(start,start+csize);
    let out;
    if(method===0)out=raw.slice();
    else if(method===8)out=new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).arrayBuffer());
    else throw new Error(name+" uses a compression this page can't read");
    if(out.length!==size)throw new Error(name+" did not unpack whole");
    return out;
  }
  return null;
}

// Files in an updater's FS.bin. It holds several directory copies: an entry
// whose byte 11 is 00 is superseded, and the last valid entry for a name wins.
const DIR_AT=0x3000,DATA_AT=0xA000,CLUSTER=0x1000,CL_HDR=6;
function fsBinFiles(img){
  const v=view(img),files=new Map();
  for(let at=DIR_AT;at+32<=DATA_AT&&at+32<=img.length;at+=32){
    if(img[at+16]===0xff||img[at+11]!==0xff)continue;
    let name="";for(let i=16;i<28&&img[at+i]!==0xff;i++)name+=String.fromCharCode(img[at+i]);
    name=name.replace(/\0+$/,"");
    const size=v.getUint32(at+12,true),out=new Uint8Array(size),seen=new Set();
    let cl=v.getUint16(at+8,true),got=0;
    while(got<size){
      const base=DATA_AT+cl*CLUSTER;
      if(cl===0xffff||seen.has(cl)||base+CL_HDR>img.length){got=-1;break;}
      seen.add(cl);
      const next=v.getUint16(base+2,true),used=v.getUint16(base+4,true);
      if(got+used>size){got=-1;break;}
      out.set(img.subarray(base+CL_HDR,base+CL_HDR+used),got);got+=used;cl=next;
    }
    if(got===size)files.set(name,out);
  }
  return files;
}

// The stock effects in an updater (the .zip as Zoom ships it, or its FS.bin),
// stripped as Effect Manager installs them: [{file, data}], by name.
async function updaterEffects(bytes){
  const b=bytes instanceof Uint8Array?bytes:new Uint8Array(bytes);
  let img=b;
  if(b[0]===0x50&&b[1]===0x4b){
    img=await unzipOne(b,n=>!n.startsWith("__MACOSX/")&&/(^|\/)FS\.bin$/.test(n));
    if(!img)throw new Error("No FS.bin in this zip. Use Zoom's Mac updater .zip (it works for this on any computer), or FS.bin from it.");
  }
  const out=[];
  for(const [file,data] of fsBinFiles(img))if(/\.ZDL$/i.test(file))out.push({file,data:strip(data)});
  if(!out.length)throw new Error("No effects found: this doesn't look like a MultiStomp updater's FS.bin.");
  return out.sort((a,b)=>a.file<b.file?-1:a.file>b.file?1:0);
}

const api={strip,updaterEffects,fsBinFiles,unzipOne};
if(typeof module!=='undefined')module.exports=api;else root.ZdlStrip=api;
})(globalThis);
