/* Compatible NAM -> checked fixed-engine ZDL. No uploaded code is executed. */
(function(root){
'use strict';
const SlotIdentity=typeof module!=='undefined'?require('./slot_identity.js'):root.SlotIdentity;
const CoverArt=typeof module!=='undefined'?require('./cover_art.js'):root.CoverArt;
const D=[1,3,7,17,41,101,239,1,3,7,17,41,101,239,1,13,1,3,7,17,41,101,239];
const K=[...Array(14).fill(6),15,15,...Array(7).fill(6)];
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
function need(ok,message){if(!ok)throw Error(message);}
function inspectModel(model){
 need(model?.architecture==='WaveNet','This is not a supported WaveNet model.');
 const c=model.config,l=c?.layers?.[0];
 need(c?.layers?.length===1 && c.head===null,'Only single-stack A2 Lite models are supported.');
 need(l.channels===3 && l.bottleneck===3 && l.input_size===1 && l.condition_size===1,'This model is too large or has a different channel layout. Choose the 3-channel A2 Lite version.');
 need(same(l.dilations,D)&&same(l.kernel_sizes,K),'This model uses a different layer layout.');
 need(l.head?.out_channels===1 && l.head.kernel_size===16 && l.head.bias===true,'Unsupported output layer.');
 need(l.layer1x1?.active===true&&l.layer1x1.groups===1&&l.head1x1?.active===false&&l.groups_input===1&&l.groups_input_mixin===1,'Unsupported channel mixing.');
 need(Array.isArray(l.activation)&&l.activation.length===23&&l.activation.every(a=>a?.type==='LeakyReLU'&&a.negative_slope===0.01),'Unsupported activation; this engine requires LeakyReLU 0.01.');
 need(same(l.gating_mode,Array(23).fill('none')),'Gated networks are not supported.');
 need(!l.secondary_activation || same(l.secondary_activation,Array(23).fill(null)),'Secondary activations are not supported.');
 need(!l.slimmable,'Nested slimmable layers are not supported.');
 for(const [key,value] of Object.entries(l)) if(key.includes('film'))need(!value?.active,'Conditioned FiLM layers are not supported.');
 need(Array.isArray(model.weights)&&model.weights.length===1871,'Expected exactly 1,871 model weights.');
 need(model.weights.every(w=>typeof w==='number'&&Number.isFinite(w)&&Number.isFinite(Math.fround(w))),'The capture contains invalid or out-of-range weights.');
 return model;
}
function selectModel(root){
 need(root&&typeof root==='object','The file is not a NAM model.');
 need(root.sample_rate===44100||root.sample_rate===48000,'Only 44.1 kHz and 48 kHz captures are supported.');
 if(root.architecture==='SlimmableContainer'){
  need(Array.isArray(root.config?.submodels),'The model has no submodels.');
  const reasons=[];
  for(const [index,entry] of root.config.submodels.entries()){
   try{return {model:inspectModel(entry.model),submodel:index,sampleRate:root.sample_rate};}
   catch(e){reasons.push(e.message);}
  }
  throw Error('No compatible A2 Lite submodel found. '+(reasons[0]||'The container is empty.'));
 }
 return {model:inspectModel(root),submodel:null,sampleRate:root.sample_rate};
}
function reorder(model){
 // NAM stores convolution [out][in][tap]; the fixed engine uses [tap][out][in].
 const w=model.weights,out=w.slice(0,3);let at=3;
 for(const k of K){
  for(let t=0;t<k;t++)for(let o=0;o<3;o++)for(let i=0;i<3;i++)out.push(w[at+(o*3+i)*k+t]);
  at+=9*k;out.push(...w.slice(at,at+18));at+=18;
 }
 out.push(...w.slice(at));need(out.length===1871,'Internal weight-layout error.');return out;
}
async function sha256(bytes){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');}
async function convert(model,template,manifest){
 const selected=selectModel(model);
 need(manifest.format===1&&manifest.weights_count===1871,'Unsupported engine template.');
 const original=new Uint8Array(template);
 need(original.length===manifest.bytes && await sha256(original)===manifest.sha256,'The engine template is damaged or outdated. Reload the page.');
 const start=manifest.weights_offset,ver=manifest.version_offset;
 need(Number.isInteger(start)&&start>=76&&start+1871*4<=original.length&&ver===68,'Invalid engine offsets.');
 need(/^\d\.\d{2}$/.test(manifest.output_version),'Invalid output version.');
 const out=original.slice(),view=new DataView(out.buffer);
 reorder(selected.model).forEach((w,i)=>view.setFloat32(start+i*4,w,true));
 out.fill(0,ver,ver+8);out.set(new TextEncoder().encode(manifest.output_version),ver);
 return {bytes:out,report:{capture:String(model.metadata?.name||'Custom NAM').slice(0,160),creator:String(model.metadata?.modeled_by||'').slice(0,160),version:manifest.output_version,sourceSampleRate:selected.sampleRate,pedalSampleRate:44100,submodel:selected.submodel,weights:1871,sha256:await sha256(out),engineSha256:manifest.sha256,note:'Replaces the capture in NAMLite for all patches using it. Hardware fidelity and available DSP headroom are not guaranteed.'}};
}
const REGISTRY_KEY='namlite-captures-v1';
// 216 capture slots. 1-8 keep FXIDs 900-907; 9-16 are 950-957 (908-913 were the
// retired CabIR bank and NAM test effects, which may still sit on a pedal);
// 17-216 are 500-699, made in the browser from one base template
// (slot_identity.js). IDs are permanent: patches store them.
const NAM_SLOTS=216;
function namFxid(slot){return slot<=8?899+slot:slot<=16?941+slot:483+slot;}
// Starts with a LETTER: slots 10-16 put two digits after 'NAM', so a slot-1
// name starting with a digit could otherwise read as one of them on the pedal.
function shortName(value){
 const name=String(value).trim();need(/^[a-zA-Z][a-zA-Z0-9_-]{0,7}$/.test(name),'Use 1–8 letters, numbers, hyphens or underscores for the short name, starting with a letter.');return name;
}
// The name the PEDAL shows. Stock effect names are at most 9 characters and
// the field is 12 bytes; 'NAM-' + 8 filled it with no terminator and broke the
// pedal's screen (issue #5). Patch Editor and filenames keep the full name.
const PEDAL_NAME_CHARS=5;
function pedalName(name){return 'NAM-'+shortName(name).slice(0,PEDAL_NAME_CHARS);}
function samePedalName(a,b){return a.slice(0,PEDAL_NAME_CHARS).toLowerCase()===b.slice(0,PEDAL_NAME_CHARS).toLowerCase();}
function patchId(fxid){return (((fxid&63)<<17)|(((fxid>>6)&1)<<30)|(((fxid>>7)&7)<<8)|(8<<1))>>>0;}
function readRegistry(storage){
 try{const entries=JSON.parse(storage.getItem(REGISTRY_KEY)||'[]');return Array.isArray(entries)?entries.filter(e=>Number.isInteger(e.slot)&&e.slot>=1&&e.slot<=NAM_SLOTS&&/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,7}$/.test(e.shortName)):[];}catch{return [];}
}
function remember(storage,report){
 const entries=readRegistry(storage).filter(e=>e.slot!==report.slot);
 need(!entries.some(e=>e.shortName.toLowerCase()===report.shortName.toLowerCase()),'That short name belongs to another capture slot. Choose a different name.');
 need(!entries.some(e=>samePedalName(e.shortName,report.shortName)),'Another capture slot already shows as '+pedalName(report.shortName)+' on the pedal. Change the first '+PEDAL_NAME_CHARS+' letters.');
 entries.push(report);storage.setItem(REGISTRY_KEY,JSON.stringify(entries));
}
// The pedal cuts ZDL basenames to 8 characters, and two installed files whose
// cut-down names match freeze it on boot (docs/SAFE-DSP-RULES.md). Every
// 'NAMLite-<name>' became 'NAMLite-', so any two captures froze the pedal.
// 'NAM<slot><name>' is 8 characters at most and unique per slot: 4 name chars
// for slots 1-9, 3 for 10-99, 2 for 100-216 (names start with a letter, so the
// slot digits always end where the name begins: 'NAM1'+'0…' can never equal
// slot 10's 'NAM10…').
function fileName(slot,name){return 'NAM'+slot+shortName(name).slice(0,slot<10?4:slot<100?3:2)+'.ZDL';}
async function convertNamed(model,template,manifest,slot,name,icon,opts={}){
 name=shortName(name);
 need(manifest.format===2,'Unsupported multi-capture engine.');
 let selected;try{selected=SlotIdentity.slotMeta(manifest,slot);}catch{selected=null;}
 // Slots past the shipped templates: `template` is the shared base; make this slot from it.
 if(selected&&selected.generated){template=await SlotIdentity.generateSlot(template,manifest,slot,sha256);selected={...selected,bytes:template.length,sha256:await sha256(template)};}
 need(selected&&selected.fxid===namFxid(slot)&&selected.id===patchId(selected.fxid),'Invalid capture identity.');
 const result=await convert(model,template,{...manifest,...selected,format:1});
 const at=selected.name_offset;need(Number.isInteger(at)&&at>=76&&at+12<=result.bytes.length,'Invalid display name offset.');
 const display=pedalName(name);result.bytes.fill(0,at,at+12);result.bytes.set(new TextEncoder().encode(display),at);
 // Eco+ (engine 0.26): the correction filter fitted for this capture (nam_response.js fitEcoEq).
 if(Number.isInteger(selected.eco_eq_offset)){
  const c=opts.ecoEq;need(Array.isArray(c)&&c.length===15&&c.every(Number.isFinite),'Eco+ needs its correction filter.');
  const at=selected.eco_eq_offset;need(at>=76&&at+64<=result.bytes.length,'Invalid Eco+ offset.');
  const view=new DataView(result.bytes.buffer,result.bytes.byteOffset);c.forEach((v,i)=>view.setFloat32(at+4*i,v,true));
 }
 // Split (engine 0.26): which output gets the amp; the other gets the dry guitar.
 if(Number.isInteger(selected.split_route_offset)){
  const route=opts.split;need(route===1||route===2,'Choose which output gets the amp.');
  const at=selected.split_route_offset;need(at>=76&&at+16<=result.bytes.length,'Invalid split offset.');
  const v=new DataView(result.bytes.buffer,result.bytes.byteOffset);   // amp factor of each side: L, R
  v.setFloat32(at,route===1?1:0,true);v.setFloat32(at+4,route===2?1:0,true);
 }
 // The pedal-screen picture: the chosen icon and the name (cover_art.js).
 if(manifest.cover){icon=icon||manifest.cover.default_icon;CoverArt.writeCover(result.bytes,selected,manifest.cover,name,icon);}
 Object.assign(result.report,{slot,fxid:selected.fxid,id:selected.id,shortName:name,icon:icon||null,displayName:display,name:'NAMLite-'+name,filename:fileName(slot,name),sha256:await sha256(result.bytes),note:'Only replaces the chosen capture slot. Other capture slots and original NAMLite are unchanged. Multiple simultaneous models may exceed pedal DSP capacity.'});
 return result;
}
const api={selectModel,reorder,convert,convertNamed,shortName,pedalName,samePedalName,PEDAL_NAME_CHARS,fileName,patchId,namFxid,NAM_SLOTS,readRegistry,remember,REGISTRY_KEY,sha256};
if(typeof module!=='undefined')module.exports=api;else root.NAMLoader=api;
})(globalThis);
