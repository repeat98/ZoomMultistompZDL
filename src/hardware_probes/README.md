# Hardware Probes

This directory contains diagnostic ZDLs used to reverse-engineer the Zoom
runtime ABI. They are not Airwindows ports and are not part of the normal
release set in `dist/`.

Build one probe by name:

```bash
python3 -B build_all.py ctxmap
python3 -B build_all.py descsize
python3 -B build_all.py initprobe
```

Build release effects plus every probe:

```bash
python3 -B build_all.py --all
```

Probe artifacts built through `build_all.py` are moved to `build/probes/`.
Keep `dist/` for working release effects only.

Each probe keeps its own `manifest.json`, `build.py`, and DSP source. Probe
build scripts reuse the shared linker and helper code from `build/` and
`src/airwindows/common/`.

## Writing a probe that is worth flashing

Two lessons from the `_init` materialization work, where four "candidate fix"
flashes each froze the pedal and taught nothing, and one probe that did nothing
at all located the fault immediately.

**Make it fail safe.** `matprobe` exists to answer "did params materialize at
load", so its Gain knob **defaults to 0**. An unmaterialized load is therefore
*silent* — an unambiguous signal — rather than some sound you have to judge.
Design the failure to be legible before you design the probe.

**Flash the question, not the answer.** The probe that settled the `_init`
question was the frame with **zero** handler calls in it. It could not fix
anything; it only asked "can our `_init` frame execute at load?". It booted,
which put the fault squarely in the handler calls after three fixes had guessed
wrong. Bisect first:

```bash
# the frame only -- no handler calls at all
ZDL_MATERIALIZE_INIT=1 ZDL_MATERIALIZE_INIT_MAX_CALLS=0 \
  python3 -B src/hardware_probes/matprobe/build.py

# ...then 1, 2, ... to find which call is fatal
ZDL_MATERIALIZE_INIT=1 ZDL_MATERIALIZE_INIT_MAX_CALLS=1 \
  python3 -B src/hardware_probes/matprobe/build.py
```

**Verify what was actually emitted.** `python3 -B build/disassemble_zdl.py
build/probes/MatProb.ZDL` — check the bytes that will be on the pedal, not the
template you think you assembled.

**A probe in `dist/` is a shipping bug.** The install docs tell people to point
Effect Manager at `dist/`, so a stray diagnostic ends up on a stranger's pedal.
`build_all.py` checks for this; a hand-run per-effect `build.py` writes to
`dist/` and does **not**, so move the file yourself. EdgeWatch and MatProb have
each escaped that way.

## Current probes of note

| Probe | fxid | Question it answers |
|---|---|---|
| `matprobe` | 496 | Did `_init` materialize params at load? Gain defaults to 0, so no = silence. |
| `ctxmap`, `ctxnib`, `ctxgate`, `ctxwatch` | | Which `ctx[]` slots exist and what is in them. |
| `stateping`, `stateiso`, `statecomb` | | Per-instance state block behaviour. |
| `desccomb`, `descsize`, `desciso` | | Arena descriptor bounds. |
| `initprobe` | | `_init` entry conditions. |
