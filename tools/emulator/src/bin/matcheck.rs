//! Check the normalized custom-effect parameter contract, not arbitrary stock DSP.
//! Requires the manifest's user-knob count and an explicit expected load bypass flag.
//! An emulator pass does not establish firmware readiness on hardware.
#[path = "../matcheck_assertions.rs"]
mod assertions;
use ziddle_emu::engine::AudioEngine;
use ziddle_emu::runtime::RuntimeHost;

const PARAMS_ADDR: u32 = 0x20000100;
const BUDGET: u64 = 40_000_000;

fn snapshot(host: &RuntimeHost, count: usize) -> Vec<Result<f32, String>> {
    std::iter::once(0).chain(5..5 + count).map(|slot| {
        host.harness.mem.read_u32(PARAMS_ADDR + slot as u32 * 4)
            .map(f32::from_bits).map_err(|e| format!("{e:?}"))
    }).collect()
}

fn check(label: &str, actual: &[Result<f32, String>], expected: &[f32]) -> bool {
    let failures = assertions::mismatches(actual, expected);
    println!("   {label}: {actual:?}");
    for failure in &failures { println!("      {failure}"); }
    println!("   {label}: {}", if failures.is_empty() { "PASS" } else { "FAIL" });
    failures.is_empty()
}

fn run(path: &str, count: usize, bypass: f32) -> Result<bool, String> {
    let bytes = std::fs::read(path).map_err(|e| e.to_string())?;
    let knobs: Vec<f32> = (1..=count).map(|i| i as f32 * 11.0).collect();
    let expected: Vec<f32> = std::iter::once(bypass)
        .chain(knobs.iter().map(|v| v / 100.0)).collect();
    let mut eng = AudioEngine::load(&bytes, &knobs, 100.0, BUDGET)
        .map_err(|e| format!("load failed: {e}"))?;
    let r = eng.load_report();
    let init_ok = r.init_present && r.init_completed && r.init_unimplemented_hits == 0;
    println!("   init: present={} completed={} unimplemented={}",
        r.init_present, r.init_completed, r.init_unimplemented_hits);
    // Observe bypass without set_engaged(): that would repair the state under test.
    let before_ok = check("after init (bypass, all user params)",
        &snapshot(eng.host_mut(), count), &expected);
    let mut handlers_ok = true;
    if let Err(e) = eng.host_mut().run_edit_handlers() {
        println!("   handler execution failed: {e}");
        handlers_ok = false;
    }
    let ep = eng.host_mut().edit_pass();
    println!("   handlers called={} failed={:?}", ep.called, ep.failed);
    handlers_ok &= ep.failed.is_empty() && ep.called >= count;
    let after_ok = check("after handlers (bypass, all user params)",
        &snapshot(eng.host_mut(), count), &expected);
    Ok(init_ok && before_ok && handlers_ok && after_ok)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    // Explicit count avoids silently testing only six knobs or inferring the count
    // from symbols (which can include aliases and non-user edit handlers).
    let parsed = (|| {
        if args.len() < 5 || args[0] != "--params" || args[2] != "--bypass" { return None; }
        let count = args[1].parse::<usize>().ok()?;
        let bypass = args[3].parse::<u8>().ok()?;
        if !(1..=9).contains(&count) || bypass > 1 { return None; }
        Some((count, bypass as f32))
    })();
    let Some((count, bypass)) = parsed else {
        eprintln!("usage: matcheck --params N --bypass 0|1 file.ZDL [more with same knob count ...]");
        std::process::exit(2);
    };
    let mut passed = true;
    for path in &args[4..] {
        println!("== {path} ==");
        match run(path, count, bypass) {
            Ok(ok) => passed &= ok,
            Err(e) => { eprintln!("   FAIL: {e}"); passed = false; }
        }
    }
    std::process::exit(if passed { 0 } else { 1 });
}
