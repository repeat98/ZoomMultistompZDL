const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const A=require('../cover_art.js'),N=require('../nam_loader.js'),C=require('../cab_loader.js');
const base=path.join(__dirname,'..'),sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const man=f=>JSON.parse(fs.readFileSync(path.join(base,f)));
const covers=[man('nam_template/multi.json').cover,man('nam_template_eco/multi.json').cover,man('cab_template/cab.json').cover];

test('covers and thumbnails match the Python drawings byte for byte',()=>{
 for(const cov of covers)for(const c of cov.check){
  const px=A.draw(cov,c.name,c.icon);
  assert.equal(sha(A.picture(cov,px)),c.picture,`${cov.kind} picture ${c.name}/${c.icon}`);
  assert.equal(sha(A.thumbnail(px)),c.thumbnail,`${cov.kind} thumbnail ${c.name}/${c.icon}`);
 }
});

test('at least 20 icons; every icon with any name fits the reserved picture area',()=>{
 const names=['','a','WWWWWWWW','MMMMMMMM','88888888','smokey','Z-9_x'];
 for(const cov of covers){
  assert.ok(cov.icons.length>=20,`${cov.kind}: ${cov.icons.length} icons`);
  for(const {id} of cov.icons)for(const n of names)assert.equal(A.picture(cov,A.draw(cov,n,id)).length,cov.capacity);
 }
 assert.throws(()=>A.draw(covers[0],'x','no-such-icon'),/Unknown icon/);
});

test('the name and icon land in the file; nothing else moves',async()=>{
 const m=man('cab_template/cab.json'),t=fs.readFileSync(path.join(base,'cab_template',m.slots[0].file));
 const fit=C.fit((()=>{const x=new Float64Array(600);x[2]=1;return x;})(),{start:'staged'});
 const a=(await C.fillCab(t,m,1,fit,'sm57','skull')).bytes,b=(await C.fillCab(t,m,1,fit,'sm57','heart')).bytes,s=m.slots[0];
 for(let i=0;i<a.length;i++)if(a[i]!==b[i])assert.ok(i>=s.picture_offset&&i<s.picture_offset+m.cover.capacity,`byte ${i} changed outside the picture`);
 assert.deepEqual(Array.from(a.slice(s.picture_offset,s.picture_offset+m.cover.capacity)),Array.from(A.picture(m.cover,A.draw(m.cover,'sm57','skull'))));
});
