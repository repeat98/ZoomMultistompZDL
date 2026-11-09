# NAMTime timing diagnostic

NAMTime 0.01 — TREC/amptrec callback timing diagnostic
Install NAMTime.ZDL and select NAMTime under Delay, alone in an empty patch.
Leave Input44, Output27, Mix100. Keep listening volume low.
Play briefly, then stop after about2seconds and record10seconds of beep groups.
After measuring, the neural engine stops and dry-through plus tones remain.
Lower-pitched groups report average elapsed neural callback time;
higher-pitched groups report the longest observed callback time.
Each group repeats in an alternating six-second cycle:
1 beep: timer unavailable/stopped; inconclusive.
2 beeps: below50% of the calibrated callback interval.
3 beeps:50–80%.
4 beeps:80–100%.
5 beeps:100% or more.
No beeps, a frozen interface, or other unexpected behavior: report it.
Bypass then re-enable to restart. Do not adjust controls during measurement.
Separate effect ID910; does not replace any NAM capture.
The probe reads TSCL but never enables/resets the timer or changes clocks/cache.
It first measures4096 low-load callback intervals, warms the actual neural
capture, and times4096 calls. Elapsed timing may include interrupts. This is
not total pedal CPU usage; low readings do not establish whole-chain headroom.
The timing wrapper also changes code layout. Hardware results are pending.

Build requires the generated private TREC header at
`build/probes/namlite/amptrec-audit/nam_kernel_pedal.h`.
Run build.py, validate.py and validate_binary.py (the latter takes the output directory).
Host tests cover mocked timer rollover, thresholds, mean/peak beep counts,
stopped timer, guards and bypass reset. Binary audit checks coefficient tables,
relocations and parameter initialization. Actual target emulator runs initialization,
controls and the stopped-timer reporting path with no unsupported instructions;
that run does not validate the timed neural path or real hardware timing.
