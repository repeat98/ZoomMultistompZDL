// Named covers for NAM and CabIR files: the pedal-screen picture and the
// Effect Manager thumbnail, with the user's icon and name.
//
// A port of build/capture_art.py (named_canvas / encode_zoom_rle) and
// make_em_thumbnails.render. The manifest's `cover` block carries the bare
// panel, each icon as a mask and the font, all drawn by the Python; `check`
// holds hashes of Python-drawn covers that this code must reproduce
// (tools/tests/cover_art.test.cjs). Templates reserve `capacity` bytes for the
// picture, so writing one never moves anything else in the file.
(function(root){
'use strict';
function need(ok,msg){if(!ok)throw Error(msg);}
function unb64(s){if(typeof Buffer!=='undefined')return new Uint8Array(Buffer.from(s,'base64'));const b=atob(s),o=new Uint8Array(b.length);for(let i=0;i<b.length;i++)o[i]=b.charCodeAt(i);return o;}
// 128x64 pixels, 1 = ink (black on the pedal's screen), row-major.
function fromBits(bits){const p=new Uint8Array(128*64);for(let i=0;i<p.length;i++)p[i]=(bits[i>>3]>>(7-(i&7)))&1;return p;}
function icons(cover){return cover.icons.map(({id,label})=>({id,label}));}
function nameText(cover,name){return Array.from(String(name).toUpperCase().slice(0,8),ch=>ch in cover.font?ch:' ').join('');}
function nameScale(cover,n){
 const [x0,y0,x1,y1]=cover.name_box,[mx,my]=cover.name_scale_max;
 const sx=Math.max(1,Math.min(mx,Math.floor((Math.floor((x1-x0+2)/Math.max(1,n))-1)/3)));
 const sy=Math.max(1,Math.min(my,Math.floor((y1-y0+1)/5),sx+1));
 return [sx,sy];
}
// The cover's pixels: bare panel, the icon's white pixels, then the name in white.
function draw(cover,name,icon){
 const p=fromBits(unb64(cover.base)),it=cover.icons.find(i=>i.id===(icon||cover.default_icon));
 need(it,'Unknown icon.');
 const m=fromBits(unb64(it.mask));for(let i=0;i<p.length;i++)p[i]^=m[i];
 const text=nameText(cover,name||'');if(!text.trim())return p;
 const [sx,sy]=nameScale(cover,text.length),[x0,y0,x1,y1]=cover.name_box;
 const w=text.length*(3*sx+1)-1,h=5*sy;
 let x=x0+Math.floor((x1-x0+1-w)/2);const y=y0+Math.floor((y1-y0+1-h)/2);
 const px=(X,Y)=>{if(X>=0&&X<128&&Y>=0&&Y<64)p[Y*128+X]=0;};
 for(const ch of text){
  cover.font[ch].forEach((row,yy)=>{for(let xx=0;xx<row.length;xx++)if(row[xx]==='1')
   for(let Y=y+yy*sy;Y<=y+(yy+1)*sy-1;Y++)for(let X=x+xx*sx;X<=x+(xx+1)*sx-1;X++)px(X,Y);});
  x+=3*sx+1;
 }
 return p;
}
// Zoom's column-major 1-bpp RLE (screen_image.encode_zoom_rle), zero-padded to `capacity`.
function picture(cover,pixels){
 const raw=[];for(let yx=0;yx<8;yx++)for(let x=0;x<128;x++){let b=0;for(let z=0;z<8;z++)if(pixels[(yx*8+z)*128+x])b|=1<<z;raw.push(b);}
 const out=[];let i=0;
 while(i<raw.length){
  if(i+1<raw.length&&raw[i]===raw[i+1]){let j=i+2;while(j<raw.length&&raw[j]===raw[i])j++;j=Math.min(j,i+257);out.push(raw[i],raw[i],j-i-2);i=j;}
  else out.push(raw[i++]);
 }
 while(out.length%4)out.push(0);
 need(out.length<=cover.capacity,'This cover is too detailed to fit the pedal file.');
 const blob=new Uint8Array(cover.capacity);blob.set(out);return blob;
}
// Effect Manager icon: 128x96 RGBA, black ink, transparent ground, the cover
// stretched by the LCD's pixel aspect (PIL NEAREST sampling) and centred.
const PIXEL_ASPECT=1.4;
function thumbnail(pixels){
 const h=Math.min(96,Math.round(128*64/128*PIXEL_ASPECT)),top=Math.floor((96-h)/2),rgba=new Uint8Array(128*96*4);
 for(let i=0;i<128*96;i++){rgba[4*i]=255;rgba[4*i+1]=255;rgba[4*i+2]=255;}
 for(let y=0;y<h;y++){const sy=Math.min(63,Math.floor((y+0.5)*64/h-1e-9));          // PIL NEAREST: an exact boundary takes the row above
  for(let x=0;x<128;x++)if(pixels[sy*128+x]){const o=4*((top+y)*128+x);rgba[o]=0;rgba[o+1]=0;rgba[o+2]=0;rgba[o+3]=255;}}
 return rgba;
}
// Write the cover into a slot's bytes at the template's reserved picture area.
function writeCover(bytes,meta,cover,name,icon){
 const at=meta.picture_offset;need(Number.isInteger(at)&&at>=76&&at+cover.capacity<=bytes.length,'Invalid picture offset.');
 bytes.set(picture(cover,draw(cover,name,icon)),at);return bytes;
}
// Browser only: the thumbnail as a PNG blob for download.
async function thumbnailPng(pixels){
 const c=document.createElement('canvas');c.width=128;c.height=96;const g=c.getContext('2d');
 g.putImageData(new ImageData(new Uint8ClampedArray(thumbnail(pixels)),128,96),0,0);
 return new Promise(r=>c.toBlob(r,'image/png'));
}
const api={icons,draw,picture,thumbnail,thumbnailPng,writeCover,nameText};
if(typeof module!=='undefined')module.exports=api;else root.CoverArt=api;
})(globalThis);
