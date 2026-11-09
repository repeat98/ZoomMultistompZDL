//! namstate -- watch an exact-ring NAMLite's memory after every callback.
//!
//! Built to find why the exact-ring TI build resets after 14 callbacks in the
//! emulator while the same C is bit-identical on the host. Reads PedalNam
//! straight out of emulated memory and reports, per callback: magic/warm, every
//! layer's ring position (must stay < n), non-finite history per layer, and the
//! MIRROR invariant h[n..n+7] == h[0..7] (bitwise) on every plane -- tap reads
//! run into the mirror instead of wrapping, so a stale mirror is a wrong read.
//!
//! usage: namstate effect.ZDL input.f32 sizes_csv [arena_base_hex] [il]
//!   il: channels interleaved per slot (h[3q+ch]) rather than planar
//!   sizes_csv: the exact ring sizes, in layer order (from exact_rings.NEED)
use std::{env, fs};
use ziddle_emu::engine::{AudioBlock, AudioEngine};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let a: Vec<_> = env::args().collect();
    if a.len() < 4 { return Err("usage: namstate effect.ZDL input.f32 sizes_csv [arena_base_hex]".into()); }
    let z = fs::read(&a[1])?;
    let x: Vec<f32> = fs::read(&a[2])?.chunks_exact(4).map(|b| f32::from_le_bytes(b.try_into().unwrap())).collect();
    let sizes: Vec<u32> = a[3].split(',').map(|v| v.parse().unwrap()).collect();
    let base = if a.len() > 4 { u32::from_str_radix(a[4].trim_start_matches("0x"), 16)? } else { 0xc010_0000 };
    let il = a.len() > 5 && a[5] == "il";
    let mut e = AudioEngine::load(&z, &[44., 27., 100.], 100., 40_000_000)?;
    e.set_engaged(true)?; e.run_edit_handlers()?; e.set_firmware_mix(true);

    // PedalNam: 8 words, then NamState { pos,pad, input[8],output[8],gain[8], lpos[23], v[30],sum[30],z[30], history[] }
    // PedalNam header is 32 bytes; +24 with the tone stack's eq[6] (NAMSTATE_NET_OFF=56)
    let net = base + std::env::var("NAMSTATE_NET_OFF").ok().and_then(|v| v.parse().ok()).unwrap_or(32u32);
    let lpos = net + 8 + 96;
    let hist = lpos + 24 * 4 + 3 * 30 * 4;       // lpos has 24 slots (23 used)
    let rd = |e: &mut AudioEngine, addr: u32| e.host_mut().harness.mem.read_u32(addr).unwrap();
    let rf = |e: &mut AudioEngine, addr: u32| f32::from_bits(e.host_mut().harness.mem.read_u32(addr).unwrap());

    let mut reported = 0;
    for (n, c) in x.chunks_exact(8).enumerate() {
        let mut i: AudioBlock = [0.; 16];
        for j in 0..8 { i[j] = c[j]; i[j + 8] = c[j]; }
        let mut o: AudioBlock = [0.; 16];
        e.process_zoom_block(&i, &mut o)?;
        let magic = rd(&mut e, base);
        let warm = rd(&mut e, base + 16);
        let ready = rd(&mut e, base + 12);
        if ready == 0 { continue; }                        // still clearing history
        let mut problems = Vec::new();
        let mut off = 0u32;
        for (l, &nn) in sizes.iter().enumerate() {
            let stride = if il { (3 * (nn + 8) + 1) & !1 } else { (nn + 9) & !1 };
            if il {
                let p = rd(&mut e, lpos + 4 * l as u32);
                if p >= nn { problems.push(format!("L{} lpos={} >= n={}", l, p, nn)); }
                let blk = hist + 4 * off;
                let mut bad = 0;
                for k in 0..3 * nn { let v = rf(&mut e, blk + 4 * k); if !v.is_finite() || v.abs() > 1e6 { bad += 1; } }
                if bad > 0 { problems.push(format!("L{} {} bad samples", l, bad)); }
                for j in 0..24u32 {
                    let (a0, m0) = (rd(&mut e, blk + 4 * j), rd(&mut e, blk + 4 * (3 * nn + j)));
                    if a0 != m0 { problems.push(format!("L{} MIRROR[{}] 0x{:08x} != 0x{:08x}", l, j, m0, a0)); break; }
                }
                off += stride;
                continue;
            }
            let p = rd(&mut e, lpos + 4 * l as u32);
            if p >= nn { problems.push(format!("L{} lpos={} >= n={}", l, p, nn)); }
            for ch in 0..3u32 {
                let plane = hist + 4 * (off + ch * stride);
                let mut bad = 0;
                for k in 0..nn { let v = rf(&mut e, plane + 4 * k); if !v.is_finite() || v.abs() > 1e6 { bad += 1; } }
                if bad > 0 { problems.push(format!("L{} ch{} {} bad samples", l, ch, bad)); }
                for j in 0..8u32 {
                    let (a0, m0) = (rd(&mut e, plane + 4 * j), rd(&mut e, plane + 4 * (nn + j)));
                    if a0 != m0 { problems.push(format!("L{} ch{} MIRROR[{}] 0x{:08x} != h[{}] 0x{:08x}", l, ch, j, m0, j, a0)); break; }
                }
                for pad in (nn + 8)..stride {
                    if rd(&mut e, plane + 4 * pad) != 0 { problems.push(format!("L{} ch{} alignment pad written", l, ch)); }
                }
            }
            off += 3 * stride;
        }
        // head ring (32-entry, stride 34, 3 planes) and the net's working buffers
        let head = hist + 4 * off;
        for k in 0..102u32 { let v = rf(&mut e, head + 4 * k); if !v.is_finite() || v.abs() > 1e6 { problems.push(format!("HEAD[{}]={}", k, v)); break; } }
        let outp: Vec<f32> = (0..8).map(|k| rf(&mut e, net + 40 + 4 * k)).collect();
        let vv: Vec<f32> = (0..30).map(|k| rf(&mut e, lpos + 24 * 4 + 4 * k)).collect();
        let ss: Vec<f32> = (0..30).map(|k| rf(&mut e, lpos + 24 * 4 + 120 + 4 * k)).collect();
        let vmax = vv.iter().fold(0f32, |m, x| m.max(x.abs())); let smax = ss.iter().fold(0f32, |m, x| m.max(x.abs()));
        if n % 1 == 0 && magic == 0x4e41_4d32 && reported == 0 && warm > 60 && warm < 130 {
            println!("block {} ok   out[0..8]={:?}  |v|max={:.3} |sum|max={:.3}", n, outp.iter().map(|x| (x*1000.).round()/1000.).collect::<Vec<_>>(), vmax, smax);
        }
        if !problems.is_empty() || magic != 0x4e41_4d32 {
            println!("block {} magic=0x{:08x} warm={} ready={}", n, magic, warm, ready);
            println!("   out[0..8]={:?}", outp);
            println!("   |v|max={} |sum|max={}", vmax, smax);
            for p in problems.iter().take(12) { println!("   {}", p); }
            reported += 1;
            if reported >= 4 { break; }
        }
    }
    if reported == 0 { println!("no problems observed"); }
    Ok(())
}
