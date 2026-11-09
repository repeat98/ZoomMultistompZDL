# Live param edits over SysEx: the slot rule

**Confirmed on hardware 2026-07-31.** Recorded here because this cost a very long
debugging session — an earlier one-line note said the same thing and was overruled.

> **NOTE, 2026-08-18. A correction that was itself wrong.**
> On 2026-08-14 this file carried a banner saying the slot rule was not a
> property of the pedal, because stock effects appeared to take live `0x31`
> edits on all six slots. **That test was confounded**: PE had auto-apply ON at
> the time, so every knob move was being followed by a patch write and a bypass
> toggle. What it showed was that the AUTO-APPLY PATH works on slots 4-6, not
> that live `0x31` does.
>
> Acting on it broke the editor -- live edits were re-enabled for all six slots
> and the auto-apply fallback removed, after which slot 4-6 knobs did nothing at
> all, not even move the pedal's display. Reverted.
>
> The slot rule below stands. What remains genuinely open is the separate
> question of this repo's synthesised edit handlers for knobs 4+, which is a
> different axis entirely -- see "Where the slot 4-6 asymmetry actually comes
> from", read with this note in mind.

## The rule

The MS-70CDR honours live `0x31` parameter edits **only for the early effect
slots**. For the later slots the identical message is accepted onto the wire and
silently ignored.

```
F0 52 00 61 31 <slot> <paramIdx> <lo7> <hi7> F7
```

* **slots 1-3** (`<slot>` = 0..2) — the value takes effect immediately.
* **slots 4-6** (`<slot>` = 3..5) — ignored. These need a buffer write plus a
  bypass bounce on that slot (see "the param cache" below). No store required.

All six slots were tested individually (2026-07-31) using CUSTOM effects, so the
1-3 / 4-6 boundary is measured rather than inferred -- but measured only for this
repo's effects. Retesting with a STOCK effect (2026-08-14) showed no boundary at
all, which is what exposed the real cause. The first clue was moving GenLoss from slot 4 to
slot 1: its knobs began responding instantly with no change to the effect at all
— same ZDL, same fxid, same descriptor.

## The asymmetry

Direction matters, and only one direction is limited:

| direction | slots 1-3 | slots 4-6 |
|---|---|---|
| editor → pedal (`0x31` in) | works | **ignored** |
| pedal → editor (`0x31` out) | works | works |

The pedal emits notifications for **every** slot, including the ones whose
inbound edits it discards — so the firmware clearly understands the address. The
limitation is in the receive handler alone, not in the addressing. Pinning down
why would mean disassembling the pedal firmware, which we have not done.

## What this is NOT

Every one of these was investigated and ruled out with evidence:

* **Not the param count.** Flower (2 params) and Spool (9 params) both live-edit
  fine; GenLoss (3) did not — until it moved slot.
* **Not the "last knob" / Mix / Hiss.** Once GenLoss was in slot 1, *all three*
  knobs worked, Hiss included.
* **Not the descriptor sentinel or flags.** Our 3-param layout (`flags=0x14`,
  `pedal_max=max` on the final entry) matches stock `AUTOWAH` and `BOTTOM_B`.
* **Not the DLL descriptor count.** Verified per effect at stub offset +142:
  Flower declares 4 (2 params + 2), GenLoss declares 5 (3 + 2). Both correct.
* **Not the bit tables.** Confirmed against the pedal's own dumps: setting Hiss
  to 100 on the pedal writes `byte 75 = 0x32`, and the table decodes
  `(0x32 & 0x7f) << 1 = 100`.
* **Not which slot the pedal is displaying.** Edits still fail on slot 4 with
  that effect on screen.

## The pedal talks back

Turning a knob **on the pedal** emits the same `0x31` form, so an editor can
follow the hardware live:

```
← F0 52 00 61 31 03 04 64 00 F7     slot 4, param idx 4 = 100
```

This is emit-only; sending it back for slots 4-6 does nothing.

## Why slots 4-6 ignore a written patch — the param cache

The DSP caches a slot's parameters **when the effect is instantiated**. Writing
the edit buffer updates the patch data but never touches that cache, so the slot
keeps playing its old values. Slots 1-3 escape this only because they accept live
`0x31`, which reaches the running effect by a different path.

The cure is to make the pedal re-instantiate the effect. Flip the slot's bypass
bit off and back on:

```
0x50            edit enable
0x28 <146B>     write buffer with the target slot's on/off bit = 0   (tear down)
0x28 <146B>     write buffer again with it = 1                       (rebuild, re-reads params)
```

Nothing is stored, no program change is sent, and only the edited slot is
disturbed — so no flash wear, no audible patch blip, and the pedal's display
stays where it was. The audible cost is a brief bypass gap on that one slot.

This is the automated form of the manual workaround "change the knob, switch the
slot off, switch it back on". It is also why **"wiggle the Mix knob on the
pedal"** has always worked: the wiggle forced a re-instantiation.

### Dead end: forcing a reload instead

Recorded so it is not retried. A **bare** program change to the program the
pedal is already on is a no-op, so `0xC0 n` alone reloads nothing — this had
silently broken every "recall" in the patch editor, including effect-type
changes. Bank Select MSB/LSB followed by `0xC0 n` (what a ToneLib capture shows)
does reload, but it needs a `0x32` store to survive, wears flash, blips through
the reloaded patch, and resets the pedal's display to the patch's stored `curfx`.
The bypass bounce above is better on every count.

### Writes must not be blind

The editor re-reads the patch and re-applies **only the fields the user changed**
(tracked as dirty `slot,field` pairs). Writing a whole cached model back pushes
stale values over slots the user never touched — including pedal-side knob moves
and live `0x31` edits that already landed.

## Hardware probe: what a patch write does and does not reach

The obvious hope was that some OTHER host-owned region tracks a patch write even
when `params[]` does not -- a custom effect could then read its knobs from there
and behave identically on all six slots, with no bypass bounce and no audible
gap. `src/hardware_probes/ctxwatch/` was built to answer that. It hashes a window
behind every `ctx[]` pointer each block and beeps that word's index when a region
that had been sitting still moves.

Run on slot 4, 2026-08-14:

| Stimulus | Result |
| --- | --- |
| boot | two beeps -- alive, at least one region under watch |
| full patch write, NO bypass bounce (`0x50` + `0x28`) | **silence** |
| Apply, i.e. the same write WITH the bounce | **1 blip = `ctx[1]`, the params table** |

So a plain `0x28` to a slot-4 effect changes nothing the running DSP can see --
not the knob params, and not any other watched word.

**Narrowed by EdgeWatch, 2026-08-18.** The single blip that Apply produced was
attributed here to re-instantiation. It was not: Apply's bypass bounce flips
`params[0]`, and THAT is what changed `ctx[1]`. EdgeWatch confirms a running
effect sees `params[0]` change from a plain patch write, on every slot. So the
rule is narrower and more useful than "a patch write is invisible":

> A patch write DOES update `params[0]` (bypass). It does NOT refresh the knob
> params.

Which explains the whole shape of this file: bypass toggling always worked, knob
edits on slots 4-6 never did, and ToneLib's forced reload worked because a reload
re-reads everything. It is also what makes a footswitch-triggered effect possible
at all -- see `src/custom/stasis/`.

**The conclusion originally drawn from it was WRONG.** This section used to end
"the bypass bounce is the mechanism, not a workaround, and no effect can avoid
it", generalising a fact about PATCH WRITES into a claim about slots 4-6 as a
whole. A later test killed it outright: **stock effects accept live `0x31` knob
edits on all six slots, including 4-6.** Only OUR effects fail there. There is no
hardware rule about slot position; the asymmetry is a bug in this repo's edit
handlers. See "Where the slot 4-6 asymmetry actually comes from" below.

Coverage caveat, so the negative result is not over-read: the probe skips
`ctx[3]`-`ctx[6]` and `ctx[11]`-`ctx[14]` (arena and audio buffers, which change
every block by definition), and any pointer failing its address guard is silently
not watched. The boot beep confirms at least one region was live but does not
report how many. A word that is both unguardable and a param mirror would have
been missed -- unlikely, but not excluded.

Two things the probe established incidentally, both worth knowing:

* **The host calls a slot's audio function even when the slot is bypassed.**
  Bypass is the effect returning early on `params[0]`, not the host skipping it.
* A readout that hums continuously and re-reports on every change is unreadable
  in practice. Silence-by-default plus a one-shot-per-index latch is what finally
  produced a countable answer; three earlier runs were wasted on volume and gate
  tuning of a design that could not have given one.

## Where the slot 4-6 asymmetry actually comes from

Test: put a STOCK effect in slot 4 and turn its Mix from an editor. It responds;
custom effects from this repo were reported not to.

**Weakened, 2026-08-18.** That comparison was run with PE's auto-apply enabled,
so the stock effect was being served by a patch write plus a bypass toggle
rather than by a live `0x31`. It therefore does not isolate stock-vs-custom at
all. Oxide's failure turned out to be a `x7.14` param-scaling bug rather than
anything to do with handlers, which weakens the theory further. Treat the
handler table below as a description of how the build works, not as a diagnosis.

The clean test has still not been run: on ONE custom effect in ONE slot, with
auto-apply OFF, compare a knob backed by a verbatim-stock handler (knob 1 or 2)
against one backed by a synthesised clone (knob 4+). Spiral's Time against its
Span does it.

What differs. A custom build gets its edit handlers from three sources:

| Knob | Handler | Writes |
| --- | --- | --- |
| 1 | LineSel blob, copied verbatim from stock | `params[5]` |
| 2 | LineSel blob, copied verbatim from stock | `params[6]` |
| 3 | AIR `Fx_REV_Air_mix_edit` blob, verbatim | `params[7]` |
| 4+ | CLONED LineSel blob with knob id and param offset patched in (`_patch_linesel_knob_clone` in `build/linker.py`) | `params[8]`+ |

Knobs 1-3 are stock code. Knob 4 and beyond are synthesized, and that is the
least-proven path in the build. Note which knob "Mix" usually is on a custom
effect: the last one.

This is made much harder to notice by `zoom_param_norm01`, which returns the
DEFAULT whenever a param reads ~0:

```c
if (raw <= 0.0001f) return zoom_clamp01(fallback_norm);
```

A param that is never written is therefore indistinguishable from a knob that
does nothing -- the effect simply sits at its default and sounds fine. This is
almost certainly the long-standing "Mix knob does nothing until I wiggle it on
the pedal" problem, and it is why that went undiagnosed for so long.

NOT yet established: why the synthesized handlers would care about slot position
at all. The blob reads new knob values from a host-provided state object (see
`build/find_firmware_state_offsets.py`), so a read that is only correct in some
contexts would produce exactly this -- but that is a hypothesis awaiting a probe,
not a finding. Do not build on it.

Next test: on a custom effect in slot 4, check knobs 1-3 against knobs 4+. If the
first three respond and the rest do not, the bug is handler synthesis.

## What ToneLib actually does on slots 4-6

ToneLib drives slots 4-6 from its UI, which looks like proof that a live path
exists. It is not. A MIDI capture of ONE knob drag, watching the pedal's output:

| Emitted by the pedal during a single drag | Count |
| --- | --- |
| Bank Select CC0 + CC32, then Program Change | 16 each |
| 146-byte patch dumps | 32 |
| `0x31` live param messages | **0** |

ToneLib reloads the WHOLE PATCH on every knob step -- sixteen full
re-instantiations during one drag -- and the pedal re-announces the patch each
time. The only bytes that differ between the dumps are the param being turned.

So there is no special command and no hidden live path. Every editor that
"works" on slots 4-6 is re-instantiating constantly and hiding the seam behind
UI responsiveness. The bypass bounce is the same trick applied to ONE slot
rather than all six, which is strictly less disruptive; PE's only real
disadvantage was making it a button press instead of doing it while you drag.
PE now auto-applies with a trailing scheduler (one apply in flight, re-fired on
completion if the knob moved meanwhile), which matches ToneLib's feel.

Caveat on the capture: it recorded only the pedal's OUTPUT, so ToneLib's own
sends were never seen. What is certain is that a full patch reload accompanies
every step; what ToneLib sends to *cause* it is inferred, not observed.

## External references, and a coordinate-space trap

[shooking/ZoomPedalFun — "De re MS-70 CDR"](https://github.com/shooking/ZoomPedalFun/wiki/De-re-MS-70-CDR)
is the only other MS-70CDR-specific protocol write-up found. It independently
confirms every command this repo uses (`0x50`/`0x51` edit enable/disable, `0x29`
request → `0x28` dump, `0x31 <fx> <param+1> <lo> <hi>`, on/off as `0x31` with
param byte `00`, `0x32` store, `0xC0` load) and the 7-in-8 packing. It documents
**nothing** about per-slot live-edit limits or the param cache, so the findings
above are not recorded anywhere else.

Two corrections to it, both checked against hardware:

* It says the pedal has **5 FX slots** and that the `0x31` slot byte is "0-4 for
  FX 1-5". The MS-70CDR has **6** — confirmed on the device. `maxfx` is not
  evidence either way; it counts *populated* slots, not capacity.
* **Its byte offsets are in UNPACKED space; this repo's bit tables index the RAW
  PACKED message.** The two are not comparable. Convert with:

  ```
  raw = 5 + 8*(u // 7) + 1 + (u % 7)        # u = unpacked index
  ```

  So its "tempo is spread over bytes 109 and 110" means **raw bytes 130-131**.
  Mixing the two spaces made it look briefly as though `encodePatch` was
  clobbering the tempo. It is not: raw byte 130's `0x1c` bits decode as the
  effect count (read 5 on a patch with exactly 5 populated slots), raw 131 is
  never written, and PE touches only `0x1c` and bit 0 of 130. Tempo lives in
  bits PE leaves alone — but anything that starts writing raw 130/131 more
  broadly needs to account for it.

## Editor behaviour

`tools/patch_editor.html` (`LIVE_EDIT_SLOTS = 3`):

* slots 1-3 — live `0x31`, no flash write, nothing else disturbed
* slots 4-6 — labelled as unable to update live; **Apply → pedal** performs the
  read → merge-dirty → bypass-bounce sequence above. Optionally automatic,
  debounced to one apply per gesture (toolbar checkbox)
* incoming `0x31` mirrors the hardware into the editor for every slot, so the
  editor follows knobs turned on the pedal

## Current-build direct-edit retest

PE's removed auto-apply checkbox was not a valid direct-edit test: sendParam
also returned early for slot indices >=3. Turning auto-apply off therefore
left no outbound parameter update path in those slots. It does not provide
new hardware evidence that current binaries ignore 0x31.

Settings > Diagnostics > Test direct edits in slots 4–6 temporarily permits
0x31 in all six slots and suppresses scheduled automatic Apply. It cancels any
queued Apply first, is not persisted, and restores normal behavior when ended
or the page reloads. Do not press Apply, switch slots on/off or change effect
types during the isolated test. Listen for a real change; a display/readback
change alone does not establish DSP materialization. Compare knob 1/2 and a
later knob on the same current custom effect, then a stock effect if needed.
No hardware result yet. 18 PE Node tests pass.
