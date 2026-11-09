# Stasis 1.01 — 2026-09-11

Built in `dist/Stasis.ZDL`; PE's embedded and external effect databases are synced.
Hardware validation pending. No pedal writes or commits performed.

## Controls and behavior

The first five parameter positions are unchanged; Capture is appended as knob 6.

- Capture 0 (default): existing slot off→on capture, on→off release.
- Capture 1: live/release; record incoming audio after the short release ramp.
- Capture 2: capture and hold when entering this value. Toggle 1 then 2 to
  record another note. Allow time in 1 to replace the capture history (up to
  about 1.42 seconds at longest Length). Repeated writes of 2 do not recapture.
- In explicit mode, bypass changes do not release or retrigger the hold. This
  intentionally tolerates PE's slots 4–6 cache-refresh bounce. Release with 1.
- Loading a patch never creates a capture, even if it saved Capture=2. Select
  1 then 2 to arm a new capture. Frozen audio is not saved with the patch.
- Mix is now a true blend during a hold, with 100 fully wet. Existing patches
  with intermediate Mix values will have less dry signal during a hold.
- Idle and Mix=0 pass stereo unchanged. The captured layer is still mono.
- Capture/release uses an approximately 5.7 ms ramp. The corrected loop seam
  blends the tail into the beginning and skips the overlapping samples at wrap.
  Blur therefore also affects the effective repetition period.

## Findings and limits

Old Mix added wet over permanent dry; the old output polynomial boosted and
colored even idle audio and collapsed stereo. Both behaviors are removed.
The old seam read before the chosen loop window, causing unwanted discontinuity.
The write cursor now stays within the ring instead of growing without bound.

The original report that later Stasis instances do not retrigger has not been
reproduced on hardware. State is instance-local in the source. Explicit Capture
provides a path independent of firmware bypass edges, but firmware allocation,
CPU limits with four effects, and actual updates in all six slots remain to test.
Do not describe the hardware failure as conclusively fixed yet.

## Validation

Host tests run the production block DSP with only firmware pointer decoding
replaced. They cover exact stereo idle/Mix=0 passthrough, full-wet exclusion of
live input, three independent holds, fourth-instance capture of their sum,
release and recapture in earlier instances, bypass-bounce survival, no capture
on load, legacy stomp capture, and seam isolation from out-of-window history.
These tests do not emulate the pedal firmware or establish real-time DSP load.
TI build has no external symbols, no object relocations, no .text helper code,
and no .fardata. The release verifier checks all init handlers and PE metadata.

## Pedal acceptance test

1. Install the new Stasis.ZDL and reload PE normally. Confirm six controls.
2. With one instance, test stomp mode, then Capture 1→2. At Mix=100, playing new
   notes must not pass through the hold. Capture=1 must restore live stereo.
3. Repeat in every slot. Change Length/Blur/Tone while holding; PE Apply in
   explicit mode must not replace the capture.
4. Capture different material with three instances, and capture their combined
   output with a fourth. Release the first three using Capture=1; the fourth
   must continue. Recapture each earlier instance independently.
5. Serial instances hear upstream holds too; they are not parallel isolated
   recording tracks. Intermediate Mix values retain upstream audio for stacking.
6. Reload the patch and power-cycle: stored controls should return, but no stale
   frozen audio should appear. Old five-control patches should default Capture
   to 0; verify this when first opening them.

## Chocolate MIDI

A USB MIDI connection needs a host. The original Chocolate and Zoom can both
connect to the Mac; PE acts as the CC-to-Zoom-SysEx bridge. A passive USB cable
or hub alone does not supply that bridge. Chocolate Plus has a HOST variant;
confirm the actual model/ports before choosing a standalone connection.

PE already supports controller CC learning to the active slot's knobs. For
Capture (sixth knob), CC value 64 selects release (1), and 127 selects hold (2).
CC value 0 selects stomp mode, NOT explicit release. Configure an alternating
64/127 switch, not the usual 0/127 toggle. The current guided learn maps knobs
of the active slot; it is not a four-fixed-slot freeze footswitch preset.
Slots 4–6 still use delayed Apply, so this is not yet a guaranteed low-latency
performance route. No Chocolate or pedal MIDI hardware testing was performed.

Manufacturer Chocolate Plus software instructions (mirrored manual):
https://manuals.plus/m/b356b75d27c82ee5437424924a3a42e714ca6053bd29831753b8d9f4421d3cd1

## 1.02 correction — Capture scaling

Hardware feedback: with the slot on, Mix=100 and Capture=1, no live audio passed.
The 1.01 implementation and host test incorrectly assumed the max=2 descriptor
made the handler return 0, 0.5, 1. The cloned LineSel handler is unchanged by
parameter maximum and uses hundredths: Capture 0/1/2 reaches DSP as 0/.01/.02.
Version 1.02 decodes those hundredths. The host test now uses .01 for release and
.02 for hold. The UI values and MIDI CC mapping above are unchanged. Hardware
confirmation of this correction remains pending; replace the 1.01 binary.
