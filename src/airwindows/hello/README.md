# HELLO — minimal ZDL prototype

The smallest functional ZDL we can produce. The audio path is a verified
pass-through (the LineSel "trick book" effect, used unmodified). The point
of this plugin is **not** the DSP — it is to validate the
build → package → flash → boot loop end-to-end before porting any real
DSP code from Airwindows.

## Files

| File              | Purpose                                                  |
|-------------------|----------------------------------------------------------|
| `manifest.json`   | Declarative description of HELLO (label, INFO block).    |
| `build.py`        | Builds `HELLO.ZDL` from the manifest + LineSel template. |
| `HELLO.ZDL`       | Historical build artifact; no longer checked in.         |

## Build

```bash
python3 hello/build.py
```

This loads [stock_zdls/MS-70CDR_LINESEL.ZDL](../../../stock_zdls/MS-70CDR_LINESEL.ZDL),
patches the on-screen label slot from `LineSel` to `HELLO`, rewrites the
INFO block (`sort_index = 250` so the unit shows it as a *new* effect rather
than overwriting LineSel), and writes `HELLO.ZDL`.

Identical input + manifest produces a byte-identical output. Verify with:

```bash
cmp -l stock_zdls/MS-70CDR_LINESEL.ZDL hello/HELLO.ZDL
```

You should see exactly **8 byte differences**: one in the INFO `sort_index`,
seven in the visible-label slot.

## What this plugin does on the pedal

* Shows up in the FX picker as `HELLO`.
* Has the LineSel-style frame UI (knob_type=2) with the same two virtual
  knobs LineSel has (EFX_L / OUT_L). They still operate on the real
  LineSel DSP because that is the host ELF we're carrying.
* Audio passes through untouched when "on" (per the LineSel design,
  see optional local reference `zoom-fx-modding-ref/library/CH_2.md`).

This is intentional. We are *only* exercising the container/header/flash
path here. Real DSP work happens in the next iteration once we replace the
ELF body — see [build/README.md](../../../build/README.md) for that workflow.

## Next steps (deliberately not in this plugin)

Where real Airwindows ports will diverge from HELLO:

1. **Replace the ELF body** with a freshly linked TI C674x shared object
   that exports the same `Fx_FLT_*` symbols (entry, init, on/off,
   per-knob edit handlers, and the audio-loop function). The ZOOM
   firmware finds these by name via the `.dynsym` table.
2. **Recompute the SIZE block's `elf_size` field** — `build/zdl.py`
   already does this on save.
3. **Repaint the picture** in the `.const` section. The picture format is
   a simple RLE described in
   optional local reference `zoom-fx-modding-ref/howto/RTFM.md`; a Python
   encoder/decoder lives in optional local reference `zoom-fx-modding-ref/diy/`.
4. **Add knob captions** the same way the label is patched (anchor + offset
   into a fixed slot).

For each of these steps the same `manifest.json → build.py` pattern
applies: declare the change, let the script do the byte-poking.
