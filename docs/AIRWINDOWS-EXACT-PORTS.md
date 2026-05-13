# Airwindows Exact-Port Policy

Airwindows effects should not be called ports unless the DSP algorithm is the
Airwindows algorithm.

It is acceptable to build small hardware probes while reverse-engineering the
Zoom ABI, but those builds must be described as experiments, smoke tests, or
approximations. They should not be presented as release-quality Airwindows
ports.

## Release Criteria

An Airwindows effect is release-worthy only when:

* Parameter names, order, defaults, and display scaling match the source.
* The audio transform is the source algorithm, with only mechanical changes
  required by C674x/C99/toolchain constraints.
* Any math approximations are audibly and numerically justified, and noted.
* Persistent state behavior is equivalent across audio blocks.
* The effect survives hardware load, bypass, parameter interaction, and preset
  switching tests.

## What Counts as an Experiment

A build is experimental if it:

* Replaces the source DSP with a generic safer effect.
* Removes core state such as delay lines, filter histories, or feedback tanks.
* Compresses a source buffer size for safety.
* Replaces a sine/random/modulation subsystem with unrelated control motion.
* Uses source parameter metadata but not source DSP.

Experimental builds are useful only to isolate ABI/linker/runtime behavior.
They should have comments and documentation that make the substitution obvious.

## Resolved Size Blocker

Many interesting Airwindows effects, including `StereoChorus`, require large
persistent state. `StereoChorus` uses two `int[65536]` delay lines in the source.
Putting that state directly into `.fardata` is not acceptable for release and has
already been associated with pedal freezes in other probes.

Hardware probes now show that `ctx[3]` provides a per-instance descriptor arena
large enough for the `StereoChorus` delay lines. `Dsz689K` still wobbles, so the
confirmed lower bound is at least 705536 bytes. The two source delay arrays need
524288 bytes total.

The current task is therefore no longer "make a chorus-ish DSP"; it is:

1. Map source state into the proven `ctx[3]` arena.
2. Keep `.fardata` tiny.
3. Hardware-test load, bypass, parameter edits, and preset switching.
4. Compare against Airwindows and document any unavoidable math substitutions.

## StereoChorus Specific Finding

The current `src/airwindows/stereochorus/stereochorus.c` is the first
`ctx[3]`-backed exact-kernel attempt. It no longer uses the old 56-sample float
ring probe. Instead it lays out a small state header plus the two source-sized
`int[65536]` delay buffers inside the host descriptor arena.

The upstream Airwindows `StereoChorus` algorithm uses:

* two `int[65536]` fixed-point delay buffers;
* sine-modulated delay offset with `speed = pow(0.32 + (A / 6), 10)`;
* `depth = (B / 60) / speed`;
* per-channel "air" compensation state before the delay write;
* three-point interpolation plus the source interpolation correction term;
* `sweepL`, `sweepR`, `gcount`, `cycle`, `lastRef*`, and dither state that
  persist across blocks.

Current Zoom substitutions to verify:

* Source `double` math is implemented with float32 arithmetic for the C674x
  audio path.
* `sin()` is an inline approximation to avoid unresolved runtime math helpers.
* The original floating-point dither tail is omitted for now.
* The descriptor arena is lazily cleared over multiple audio callbacks before
  the chorus core starts, so first-enable startup is safer but not byte-identical
  to a desktop plugin constructor.

See `docs/ZDL-REVERSE-ENGINEERING-STATUS.md` for the broader ZDL/pedal map and
the current state-research plan.

## ToTape9 Specific Finding

The current `ToTape9` source is an exact-port attempt, not a finished port. It
uses a `ToTape9State` struct in `ctx[3]` instead of the old stateless
approximation, keeps `.fardata` at 0 bytes, and exposes all 9 Airwindows
parameters.

Hardware result: the current `dist/ToTape9.ZDL` crashes on load on the test
MS-70CDR. Until that load-time failure is split, `ToTape9` must be described as
a failing full-kernel probe. The next evidence needed is an audio-NOP build with
the same 9-parameter descriptor/edit-handler shape.
