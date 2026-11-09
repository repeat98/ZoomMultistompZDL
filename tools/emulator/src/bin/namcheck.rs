//! Compare actual ZDL execution with host wrapper; cycle counts exclude hardware cache/firmware.
//! Writes the L output; NAMCHECK_RIGHT=<path> also writes R.
//! NAMCHECK_PRESSES=<block,block,...> flips the effect on/off (footswitch) before those blocks.
use std::{env,fs};
use ziddle_emu::engine::{AudioBlock,AudioEngine};
fn main()->Result<(),Box<dyn std::error::Error>>{
 let a:Vec<_>=env::args().collect();if a.len()<4||a.len()>5{return Err("usage: namcheck effect.ZDL input.f32 output.f32 [knobs_csv]".into());}
 let z=fs::read(&a[1])?;let bytes=fs::read(&a[2])?;let x:Vec<f32>=bytes.chunks_exact(4).map(|b|f32::from_le_bytes(b.try_into().unwrap())).collect();
 let knobs:Vec<f32>=if a.len()==5{a[4].split(',').map(|v|v.parse()).collect::<Result<_,_>>()?}else{vec![44.,27.,100.]};
 let mut e=AudioEngine::load(&z,&knobs,100.,40_000_000)?;
 println!("load {:?}",e.load_report());
 if !e.load_report().init_clean(){return Err("Unclean emulator init; no trustworthy audio verdict".into());}
 e.set_engaged(true)?;let edit=e.run_edit_handlers()?;if edit.unimplemented_total()!=0||!e.edit_pass().failed.is_empty(){return Err("Unclean edit pass".into());}e.set_firmware_mix(true);
 let mem=&e.host_mut().harness.mem;let params:Vec<_>=(0..11).map(|i|f32::from_bits(mem.read_u32(0x20000100+i*4).unwrap())).collect();println!("params {:?}",params);
 let mut out=Vec::new();let mut right=Vec::new();let mut cycles=Vec::new();let mut all:Vec<u64>=Vec::new();
 let presses:Vec<usize>=std::env::var("NAMCHECK_PRESSES").ok().map(|v|v.split(',').filter_map(|t|t.trim().parse().ok()).collect()).unwrap_or_default();let mut eng=true;
 for (n,c) in x.chunks_exact(8).enumerate(){if presses.contains(&n){eng=!eng;e.set_engaged(eng)?;}let mut i:AudioBlock=[0.;16];for j in 0..8{i[j]=c[j];i[j+8]=c[j];}let mut o:AudioBlock=[0.;16];let h=e.process_zoom_block(&i,&mut o)?;if h.unimplemented_total()!=0{return Err(format!("Unsupported opcodes at block {}: {}",n,h.unimplemented_site_summary(10)).into());}if n>1200{cycles.push(h.cycles);}all.push(h.cycles);for v in &o[..8]{out.extend_from_slice(&v.to_le_bytes());}for v in &o[8..]{right.extend_from_slice(&v.to_le_bytes());}if n%500==0{eprintln!("block {} cycles {}",n,h.cycles);}}
 fs::write(&a[3],out)?;if let Ok(rp)=std::env::var("NAMCHECK_RIGHT"){fs::write(rp,right)?;}if let Ok(tp)=std::env::var("NAMCHECK_TRACE"){fs::write(tp,all.iter().map(|c|c.to_string()).collect::<Vec<_>>().join("\n"))?;}cycles.sort();if !cycles.is_empty(){println!("emulated callback cycles min={} median={} max={} (not physical timing)",cycles[0],cycles[cycles.len()/2],cycles[cycles.len()-1]);}Ok(())
}
