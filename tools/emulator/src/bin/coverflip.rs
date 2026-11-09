//! Test C in the emulator: toggle an effect off/on and read bytes of its cover
//! (module data is loaded at 0x80000000; the cover starts there).
//! usage: coverflip effect.ZDL <cover offset of first striped byte>
use std::{env,fs};
use ziddle_emu::engine::{AudioBlock,AudioEngine};
fn main()->Result<(),Box<dyn std::error::Error>>{
 let a:Vec<_>=env::args().collect();if a.len()!=3{return Err("usage: coverflip effect.ZDL <offset>".into());}
 let z=fs::read(&a[1])?;let off:u32=a[2].parse()?;let addr=0x8000_0000u32+off;
 let mut e=AudioEngine::load(&z,&[50.,50.,50.],100.,40_000_000)?;
 if !e.load_report().init_clean(){return Err("unclean init".into());}
 e.set_engaged(true)?;e.run_edit_handlers()?;
 let byte=|e:&mut AudioEngine|->u32{let w=e.host_mut().harness.mem.read_u32(addr&!3).unwrap();(w>>(8*(addr&3)))&0xff};
 let run=|e:&mut AudioEngine,n:usize|->Result<(),Box<dyn std::error::Error>>{for _ in 0..n{let i:AudioBlock=[0.;16];let mut o:AudioBlock=[0.;16];let h=e.process_zoom_block(&i,&mut o)?;if h.unimplemented_total()!=0{return Err("unimplemented opcode".into());}}Ok(())};
 run(&mut e,20)?;println!("on        : {:02X}",byte(&mut e));
 e.set_engaged(false)?;run(&mut e,20)?;println!("after off : {:02X}",byte(&mut e));
 e.set_engaged(true)?;run(&mut e,20)?;println!("after on  : {:02X}",byte(&mut e));
 Ok(())
}
