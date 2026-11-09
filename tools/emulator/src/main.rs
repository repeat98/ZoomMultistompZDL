//! zdlprobe -- run a .ZDL through the emulated C674x and report whether it is healthy.
//!
//! Built against Ziddle (berbasoft.com/ziddle, CC0). The point is to catch, on a
//! desktop, the faults this project has only ever caught by flashing a pedal and
//! listening: hangs, dead knobs, silence, denormal decay, NaN.
//!
//! Trust gate: the emulator reports opcodes it does not implement. If a run hits
//! any, the audio it produced is NOT evidence of anything and the report says so
//! rather than printing a confident number.
//!
//! usage: zdlprobe <file.ZDL> [--knobs a,b,c] [--wav out.wav] [--sweep] [--seconds N]

use ziddle_emu::engine::{AudioBlock, AudioEngine};
use ziddle_emu::runtime::ParamSnapshot;

const SR: usize = 44100;
const BLOCK: usize = 8; // frames per call; AudioBlock is [L;8][R;8], planar
const BUDGET: u64 = 40_000_000;

struct Args {
    path: String,
    knobs: Vec<f32>,
    wav: Option<String>,
    sweep: bool,
    bulk: bool,
    seconds: f32,
    stomp: f32,
}

fn parse_args() -> Option<Args> {
    let mut a = std::env::args().skip(1);
    let path = a.next()?;
    let (mut knobs, mut wav, mut sweep, mut seconds) = (Vec::new(), None, false, 2.0f32);
    let mut stomp = 0.0f32;
    let mut bulk = false;
    while let Some(f) = a.next() {
        match f.as_str() {
            "--knobs" => {
                knobs = a
                    .next()
                    .unwrap_or_default()
                    .split(',')
                    .filter_map(|s| s.trim().parse().ok())
                    .collect()
            }
            "--wav" => wav = a.next(),
            "--sweep" => sweep = true,
            "--bulk" => bulk = true,
            "--stomp" => stomp = a.next().and_then(|s| s.parse().ok()).unwrap_or(0.0),
            "--seconds" => seconds = a.next().and_then(|s| s.parse().ok()).unwrap_or(2.0),
            _ => {}
        }
    }
    Some(Args { path, knobs, wav, sweep, bulk, seconds, stomp })
}

/// Plucked notes: something with transients, decay and a real fundamental. A pure
/// sine hides decimation and freeze artefacts; silence hides denormal decay.
fn test_signal(n: usize) -> Vec<f32> {
    let mut v = vec![0.0f32; n];
    let notes = [110.0f32, 164.81, 220.0, 246.94];
    // Notes keep coming for the first 60% of the render, then silence.
    //
    // The old version played four notes and stopped, so a long test was mostly
    // quiet: a feedback loop never got the sustained excitation real playing
    // gives it, and Spiral's runaway -- which only shows up "after a while" --
    // could not reproduce at all. The trailing silence is what the decay/sustain
    // measurement actually reads.
    let play = (n as f32 * 0.6) as usize;
    for (i, s) in v.iter_mut().enumerate() {
        if i >= play { continue; }
        let t = i as f32 / SR as f32;
        let idx = ((t / 0.5) as usize) % notes.len();
        let f = notes[idx];
        let ph = t - ((t / 0.5) as f32).floor() * 0.5;
        let env = (-ph * 3.5).exp();
        *s = env
            * (0.6 * (2.0 * std::f32::consts::PI * f * t).sin()
                + 0.25 * (4.0 * std::f32::consts::PI * f * t).sin()
                + 0.1 * (6.0 * std::f32::consts::PI * f * t).sin());
    }
    v
}

struct Run {
    out: Vec<f32>,
    input_fall: f32,
    edit_note: String,
    diff: f32,
    peak: f32,
    rms: f32,
    nonfinite: usize,
    unimpl: u64,
    stopped: Option<String>,
    tail_rms: f32,
}

/// Change ONE knob partway through, and return only the audio from after the change.
///
/// Setting knobs at load writes the whole param block at once. Howl and Dustbox use
/// an edit-driven latch that accepts a value only when EXACTLY ONE slot moved since
/// the last block -- a bulk rewrite is treated as a patch load and deliberately
/// ignored, so the effect keeps sounding its previous values. Probing them by
/// loading with different knobs therefore measured nothing at all and reported
/// every knob dead. Turning one knob WHILE RUNNING is what a person does, and it is
/// the only way those two effects ever see a new value.
fn run_turning(
    bytes: &[u8],
    base: &[f32],
    knob: usize,
    value: f32,
    secs: f32,
    stomp: f32,
) -> Result<Run, String> {
    let mut after = base.to_vec();
    if knob < after.len() {
        after[knob] = value;
    }
    // The turn must land AFTER the stomp, never before it. Every effect here opens
    // with `if (params[0] < 0.5f) return;`, so while bypassed the DSP returns before
    // it ever reaches its knob-latch code -- a knob moved during that window is
    // simply never observed, and on the first engaged block the whole param set
    // looks changed at once, which is exactly the bulk rewrite the latch rejects.
    let at = if stomp > 0.0 { stomp + (secs - stomp) * 0.4 } else { secs * 0.4 };
    run_inner(bytes, base, secs, stomp, Some((after, at)))
}

fn run(bytes: &[u8], knobs: &[f32], secs: f32, stomp: f32) -> Result<Run, String> {
    run_inner(bytes, knobs, secs, stomp, None)
}

fn run_inner(
    bytes: &[u8],
    knobs: &[f32],
    secs: f32,
    stomp: f32,
    turn: Option<(Vec<f32>, f32)>,
) -> Result<Run, String> {
    let mut eng = AudioEngine::load(bytes, knobs, 100.0, BUDGET)
        .map_err(|e| format!("load failed: {e}"))?;
    let rep = eng.load_report();
    let mut unimpl = rep.init_unimplemented_hits;
    if !rep.init_completed && rep.init_present {
        return Err("init handler did not complete (would hang the DSP)".into());
    }

    // Every effect in this pack opens with `if (params[0] < 0.5f) return;` -- the
    // bypass flag. Without engaging, the DSP returns immediately and the probe
    // reads dead silence and calls a perfectly healthy effect broken.
    eng.set_engaged(true).map_err(|e| format!("engage failed: {e}"))?;
    // Without this the host reads the block back from the ACCUMULATOR, which only
    // the firmware's own mix stage fills. Our effects write the wet buffer (ctx[5]),
    // so the probe read silence and reported every healthy effect as SILENT.
    eng.set_firmware_mix(true);
    // Two ways a knob value can reach the DSP, and telling them apart is the point:
    //
    //   load()              seeds params[5..] DIRECTLY with the knob values.
    //   run_edit_handlers() does NOT (it calls write_environment_keeping_params,
    //                       seed_params=false). It writes the RAW knob addresses and
    //                       then runs the effect's own *_edit handlers to convert
    //                       raw -> params. If those handlers don't deliver, calling
    //                       this REPLACES good seeded values with whatever they wrote.
    //
    // So: with handlers = what the pedal actually does. Without = params forced.
    // A knob dead in the first and alive in the second is a broken edit handler,
    // not broken DSP -- which is the distinction this project has never been able
    // to make from the hardware side.
    let mut edit_note = String::new();
    if std::env::var("ZDLPROBE_NO_EDIT").is_err() {
        if let Ok(h) = eng.run_edit_handlers() {
            unimpl += h.unimplemented_total();
        }
        let ep = eng.edit_pass();
        if !ep.failed.is_empty() {
            edit_note = format!(
                "{} of {} edit handlers FAILED: {}",
                ep.failed.len(),
                ep.called,
                ep.failed
                    .iter()
                    .map(|(n, e)| format!("{n} ({e})"))
                    .collect::<Vec<_>>()
                    .join(", ")
            );
        }
    }

    if std::env::var("ZDLPROBE_DUMPPARAMS").is_ok() {
        const PARAMS_ADDR: u32 = 0x2000_0000 + 0x100;
        const KNOB_RAW_ADDR: u32 = 0x2000_0000 + 0xa00;
        let h = &eng.host_mut().harness;
        let p: Vec<String> = (0..14)
            .map(|i| match h.mem.read_u32(PARAMS_ADDR + i * 4) {
                Ok(w) => format!("{:.3}", f32::from_bits(w)),
                Err(_) => "err".into(),
            })
            .collect();
        let k: Vec<String> = (0..8)
            .map(|i| match h.mem.read_u32(KNOB_RAW_ADDR + i * 4) {
                Ok(w) => format!("{:.1}", f32::from_bits(w)),
                Err(_) => "err".into(),
            })
            .collect();
        println!("  [params] {}", p.join(" "));
        println!("  [rawknb] {}", k.join(" "));
    }

    let n = (SR as f32 * secs) as usize;
    let sig = test_signal(n);
    let mut out: Vec<f32> = Vec::with_capacity(n);
    let mut stopped = None;

    // Trigger-style effects (Stasis) fire on the params[0] TRANSITION 0->1 -- a
    // footswitch stomp -- and deliberately keep running while bypassed so the stomp
    // captures the past. Engaging before the first block means prevOn initialises
    // to 1, the edge never happens, and the effect looks stone dead with every knob
    // "broken". --stomp runs disengaged first and steps on it partway through.
    let stomp_block = if stomp > 0.0 { (SR as f32 * stomp) as usize / BLOCK } else { 0 };
    if stomp_block > 0 {
        eng.set_engaged(false).map_err(|e| format!("disengage failed: {e}"))?;
    }

    let turn_block = turn.as_ref().map(|(_, t)| (SR as f32 * t) as usize / BLOCK);
    let mut keep_from = 0usize;

    for (bi, chunk) in sig.chunks(BLOCK).enumerate() {
        if stomp_block > 0 && bi == stomp_block {
            eng.set_engaged(true).map_err(|e| format!("stomp failed: {e}"))?;
        }
        if let (Some(tb), Some((after, _))) = (turn_block, turn.as_ref()) {
            if bi == tb {
                eng.update_params(&ParamSnapshot::new(after, 100.0));
                if let Ok(h) = eng.run_edit_handlers() {
                    unimpl += h.unimplemented_total();
                }
                keep_from = out.len();
            }
        }
        let mut inb: AudioBlock = [0.0; 16];
        for (i, s) in chunk.iter().enumerate() {
            inb[i] = *s;
            inb[i + BLOCK] = *s;
        }
        let mut ob: AudioBlock = [0.0; 16];
        match eng.process_zoom_block(&inb, &mut ob) {
            Ok(h) => unimpl += h.unimplemented_total(),
            Err(e) => {
                stopped = Some(e.to_string());
                break;
            }
        }
        for i in 0..chunk.len() {
            out.push(ob[i]);
        }
    }

    // Only the audio AFTER the knob moved is evidence about that knob.
    if keep_from > 0 && keep_from < out.len() {
        out.drain(..keep_from);
    }

    // Difference from the input, as dB relative to the input's own level. A Mix=0
    // passthrough should land near -inf; this is the fidelity check, because it is
    // the one case where the correct output is known exactly in advance.
    let n_cmp = out.len().min(sig.len());
    let dsq: f64 = (0..n_cmp)
        .map(|i| {
            let d = (out[i] - sig[i]) as f64;
            d * d
        })
        .sum();
    let isq: f64 = sig[..n_cmp].iter().map(|s| (*s as f64) * (*s as f64)).sum();
    let diff = if isq > 0.0 { (dsq / isq).sqrt() as f32 } else { 0.0 };

    let peak = out.iter().fold(0.0f32, |m, s| m.max(s.abs()));
    let sq: f64 = out.iter().map(|s| (*s as f64) * (*s as f64)).sum();
    let rms = if out.is_empty() { 0.0 } else { (sq / out.len() as f64).sqrt() as f32 };
    let nonfinite = out.iter().filter(|s| !s.is_finite()).count();
    // Last 10%: catches a tail that dies into denormals after converging.
    let tail = &out[out.len().saturating_sub(out.len() / 10)..];
    let tsq: f64 = tail.iter().map(|s| (*s as f64) * (*s as f64)).sum();
    let tail_rms =
        if tail.is_empty() { 0.0 } else { (tsq / tail.len() as f64).sqrt() as f32 };

    // The test signal is plucked notes and its LAST note decays for over a second,
    // so the bare input already falls ~44x from its own average by the final tenth.
    // Judging an effect's tail against an absolute ratio therefore flagged healthy
    // effects that simply follow the input down. What matters is the tail dying
    // FASTER than the input's does.
    let in_tail = &sig[sig.len().saturating_sub(sig.len() / 10)..];
    let itsq: f64 = in_tail.iter().map(|s| (*s as f64) * (*s as f64)).sum();
    let in_tail_rms = if in_tail.is_empty() { 0.0 }
                      else { (itsq / in_tail.len() as f64).sqrt() as f32 };
    let in_rms = if sig.is_empty() { 0.0 }
                 else { (isq / n_cmp.max(1) as f64).sqrt() as f32 };
    let input_fall = if in_tail_rms > 0.0 { in_rms / in_tail_rms } else { 1.0 };

    Ok(Run { out, input_fall, edit_note, diff, peak, rms, nonfinite, unimpl, stopped, tail_rms })
}

fn write_wav(path: &str, data: &[f32]) -> std::io::Result<()> {
    let mut b = Vec::with_capacity(44 + data.len() * 2);
    let bytes = (data.len() * 2) as u32;
    b.extend(b"RIFF");
    b.extend(&(36 + bytes).to_le_bytes());
    b.extend(b"WAVEfmt ");
    b.extend(&16u32.to_le_bytes());
    b.extend(&1u16.to_le_bytes());
    b.extend(&1u16.to_le_bytes());
    b.extend(&(SR as u32).to_le_bytes());
    b.extend(&((SR * 2) as u32).to_le_bytes());
    b.extend(&2u16.to_le_bytes());
    b.extend(&16u16.to_le_bytes());
    b.extend(b"data");
    b.extend(&bytes.to_le_bytes());
    for s in data {
        b.extend(&((s.clamp(-1.0, 1.0) * 32767.0) as i16).to_le_bytes());
    }
    std::fs::write(path, b)
}

fn db(x: f32) -> String {
    if x <= 1e-9 { "  -inf".into() } else { format!("{:6.1}", 20.0 * x.log10()) }
}

fn main() {
    let Some(args) = parse_args() else {
        eprintln!("usage: zdlprobe <file.ZDL> [--knobs a,b,c] [--wav out] [--sweep] [--seconds N]");
        std::process::exit(2);
    };
    let name = std::path::Path::new(&args.path)
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let bytes = match std::fs::read(&args.path) {
        Ok(b) => b,
        Err(e) => {
            println!("{name}: cannot read: {e}");
            std::process::exit(1);
        }
    };

    let knobs =
        if args.knobs.is_empty() { vec![50.0f32; 8] } else { args.knobs.clone() };

    println!("== {name} ({} bytes) ==", bytes.len());

    if std::env::var("ZDLPROBE_DEBUG").is_ok() {
        match ziddle_emu::harness::Harness::load(&bytes) {
            Ok(h) => {
                println!("  [dbg] audio_process : {:?}", h.audio_process());
                println!("  [dbg] from_symbols  : {:?}", h.audio_process_from_symbols());
                println!("  [dbg] init          : {:?}", h.init_function());
                let syms = h.named_symbols_sorted();
                println!("  [dbg] symbols ({}):", syms.len());
                for (a, n) in syms.iter().take(24) {
                    println!("        0x{a:08x}  {n}");
                }
            }
            Err(e) => println!("  [dbg] harness load failed: {e}"),
        }
    }
    let r = match run(&bytes, &knobs, args.seconds, args.stomp) {
        Ok(r) => r,
        Err(e) => {
            println!("  FAIL  {e}");
            std::process::exit(1);
        }
    };

    // Fidelity gate first: without it every number below is unsupported.
    if !r.edit_note.is_empty() {
        println!("  {}", r.edit_note);
    }
    if r.unimpl > 0 {
        println!("  UNTRUSTWORTHY: {} unimplemented-opcode hits -- audio below proves nothing", r.unimpl);
    }
    if let Some(s) = &r.stopped {
        println!("  HANG/ABORT: {s}");
        println!("             (budget exhaustion here = the freeze that needs an Effect Manager rewrite)");
    }
    println!("  peak {} dB   rms {} dB   tail {} dB   vs-input {} dB",
           db(r.peak), db(r.rms), db(r.tail_rms), db(r.diff));
    if r.nonfinite > 0 {
        println!("  NaN/Inf samples: {}", r.nonfinite);
    }
    if r.peak < 1e-6 {
        println!("  SILENT -- effect produced no output");
    }
    if r.tail_rms > 0.0 && r.rms > 0.0 {
        let fall = r.rms / r.tail_rms;
        // 4x worse than the input's own decay, not an absolute threshold.
        if fall > r.input_fall * 4.0 {
            println!("  TAIL DIED -- falls {:.0}x vs the input's own {:.0}x (denormal decay?)",
                     fall, r.input_fall);
        }
    }

    if let Some(w) = &args.wav {
        match write_wav(w, &r.out) {
            Ok(_) => println!("  wrote {w}"),
            Err(e) => println!("  wav write failed: {e}"),
        }
    }

    // Does this effect honour a BULK param rewrite -- every knob replaced at once,
    // which is what a patch load or a slot reorder delivers? Effects with an
    // edit-driven knob latch deliberately IGNORE that and keep sounding their old
    // values until one knob moves on its own. On hardware that reads as a slot
    // going numb after a drag, with the displayed numbers still correct.
    if args.bulk {
        // Control is the SAME run with NO param change -- identical engine history,
        // identical delay contents, the only difference being whether the bulk
        // rewrite happened. Comparing against a separately-loaded run instead
        // measures how differently the two buffers filled, which is why the first
        // version of this test called Dustbox and Howl "honoured" when they are
        // precisely the two effects that ignore a bulk rewrite by design.
        let alt: Vec<f32> = knobs.iter()
            .map(|v| if *v > 50.0 { 12.0 } else { 88.0 })
            .collect();
        let secs = 3.0f32;
        let changed = run_inner(&bytes, &knobs, secs, args.stomp,
                                Some((alt, secs * 0.4)));
        let same = run_inner(&bytes, &knobs, secs, args.stomp,
                             Some((knobs.clone(), secs * 0.4)));
        match (changed, same) {
            (Ok(x), Ok(y)) => {
                let n = x.out.len().min(y.out.len());
                let d: f64 = (0..n).map(|t| {
                    let e = (x.out[t] - y.out[t]) as f64; e * e }).sum();
                let e: f64 = (0..n).map(|t| {
                    let v = y.out[t] as f64; v * v }).sum();
                let rel = if e > 0.0 { (d / e).sqrt() } else { 0.0 };
                println!("  bulk rewrite: {:<8}  (delta {})",
                    if rel > 0.01 { "honoured" } else { "IGNORED" },
                    db(rel as f32));
            }
            _ => println!("  bulk rewrite: test failed"),
        }
    }

    // Knob sweep: the most-repeated bug class in this pack is a control that does
    // nothing. Move one knob at a time and see whether the output actually moves.
    if args.sweep {
        // Sweep 2 / 50 / 100, not 0 / 50 / 100: zoom_param_norm01 treats a raw value
        // at or below 0.0001 as "not set yet" and substitutes the effect's DEFAULT,
        // so a knob at 0 reports whatever the default is and tells you nothing.
        //
        // Deadness is judged on the WAVEFORM, not on rms. A control that reorders
        // blocks or shifts a filter changes timbre while leaving level untouched --
        // judging by rms alone flags those as dead when they work perfectly.
        println!("  knob sweep (rms at 2 / 50 / 100; dead = waveform never changes):");
        for k in 0..knobs.len() {
            let mut vals = Vec::new();
            let mut waves: Vec<Vec<f32>> = Vec::new();
            let mut bad = false;
            for v in [2.0f32, 50.0, 100.0] {
                match run_turning(&bytes, &knobs, k, v, 2.0f32.max(args.stomp * 2.0), args.stomp) {
                    Ok(x) => {
                        if x.unimpl > 0 || x.stopped.is_some() { bad = true; }
                        vals.push(x.rms);
                        waves.push(x.out);
                    }
                    Err(_) => { bad = true; vals.push(0.0); waves.push(Vec::new()); }
                }
            }
            // Largest waveform difference between any pair, relative to signal level.
            let mut worst = 0.0f32;
            for i in 0..waves.len() {
                for j in (i + 1)..waves.len() {
                    let (a, b) = (&waves[i], &waves[j]);
                    let n = a.len().min(b.len());
                    if n == 0 { continue; }
                    let d: f64 = (0..n)
                        .map(|t| { let e = (a[t] - b[t]) as f64; e * e })
                        .sum();
                    let e: f64 = (0..n).map(|t| (a[t] as f64) * (a[t] as f64)).sum();
                    if e > 0.0 {
                        worst = worst.max((d / e).sqrt() as f32);
                    }
                }
            }
            let mut worst = worst;
            // A feedback control needs REPEATS before it can show itself, and a
            // delay whose beat is over a second gets barely one inside a short
            // test. Spool's Feed and Mangle's Feedbk both read stone dead at 1.5s
            // and are plainly alive at 10s. So anything that looks dead is retried
            // long before it is called dead -- only the suspicious knobs pay for it.
            if worst <= 0.001 && !bad {
                let long = (args.seconds * 5.0).max(10.0);
                let mut w2: Vec<Vec<f32>> = Vec::new();
                for v in [2.0f32, 100.0] {
                    if let Ok(x) = run_turning(&bytes, &knobs, k, v, long, args.stomp) {
                        w2.push(x.out);
                    }
                }
                if w2.len() == 2 {
                    let (a, b) = (&w2[0], &w2[1]);
                    let n = a.len().min(b.len());
                    let d: f64 = (0..n).map(|t| { let e = (a[t] - b[t]) as f64; e * e }).sum();
                    let e: f64 = (0..n).map(|t| (a[t] as f64) * (a[t] as f64)).sum();
                    if e > 0.0 {
                        worst = worst.max((d / e).sqrt() as f32);
                    }
                }
            }
            let moves = worst > 0.001;
            println!(
                "    knob {}: {} {} {}   delta {}   {}",
                k + 1,
                db(vals[0]), db(vals[1]), db(vals[2]), db(worst),
                if bad { "?" } else if moves { "moves" } else { "DEAD" }
            );
        }
    }
}
