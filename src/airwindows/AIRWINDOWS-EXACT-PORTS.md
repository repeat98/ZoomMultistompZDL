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

## Current Hard Blocker

Many interesting Airwindows effects, including `StereoChorus`, require large
persistent state. `StereoChorus` uses two `int[65536]` delay lines in the source.
Putting that state directly into `.fardata` is not acceptable for release and
has already been associated with pedal freezes in other probes.

The real task is therefore not "make a chorus-ish DSP"; it is:

1. Discover or implement a safe per-effect state strategy on Zoom MS hardware.
2. Port the exact source DSP onto that state strategy.
3. Only then ship the effect under the Airwindows name.

Until then, any substitute DSP should be treated as an ABI experiment, not an
Airwindows port.

## StereoChorus Specific Finding

The current `src/airwindows/stereochorus/stereochorus.c` is intentionally not
the Airwindows DSP. It uses a 56-sample float ring buffer so we can test small
persistent `.fardata` behavior on hardware.

The upstream Airwindows `StereoChorus` algorithm is different in kind:

* two `int[65536]` fixed-point delay buffers;
* sine-modulated delay offset with `speed = pow(0.32 + (A / 6), 10)`;
* `depth = (B / 60) / speed`;
* per-channel "air" compensation state before the delay write;
* three-point interpolation plus the source interpolation correction term;
* `sweepL`, `sweepR`, `gcount`, `cycle`, `lastRef*`, and dither state that
  persist across blocks.

So if `StChorus.ZDL` does not sound like Airwindows `StereoChorus`, that is
expected. The correct fix is not more chorus tuning; it is solving the
state/storage ABI and then moving the actual source kernel over.

See `docs/ZDL-REVERSE-ENGINEERING-STATUS.md` for the broader ZDL/pedal map and
the current state-research plan.
