# Zoom's and TI's files: kept locally

This repository publishes its own work only. Files that belong to Zoom or to
Texas Instruments stay on your computer: they are listed in `.gitignore`,
and the tools that need them read them from the same paths as before.

| Local path | What it is | Who needs it |
| --- | --- | --- |
| `stock_zdls/` | Zoom's stock effects | `build/extract_effect_db.py` (the Patch Editor's effect list), `build/analyze_stock_corpus.py`, the TapeHack template build |
| `firmware/` (except `wrap_for_dis6x.py`) | Zoom firmware images and what was extracted and disassembled from them | Firmware research only |
| `build/linesel_handlers.bin`, `build/air_knob3_edit.bin` | Edit-handler code from the stock LineSel and AIR effects | `build/linker.py`: every effect build |
| `build/divf_rts.bin` | TI's float-divide runtime routine, as found in a stock effect | `build/linker.py` |
| `build/c6xabi_attributes.bin`, `build/TI_section_flags.bin` | TI toolchain attribute and section-flag bytes | `build/linker.py` |
| `build/syncprobe*_handler*.bin` | Patched LineSel handler clones | The sync hardware probes |
| `build/exciter_outlv_edit.bin`, `build/lofidly_handlers.bin`, `ofd_zdl.txt` | Handler code and an `ofd6x` dump from the stock Exciter and LoFiDly effects | ABI notes |
| `docs/sprab89b.pdf`, `docs/sprui03f.pdf`, `docs/sprui04g.pdf` | TI manuals | Linked from [TI-PDF-NOTES.md](TI-PDF-NOTES.md) instead |

Installing and using the effects needs none of this: `dist/` and the NAM and
cab templates are complete. Building effects from source needs the four
linker files above in `build/`.

## Getting them

- **Stock effects:** from your own Zoom Effect Manager installation, which
  carries the stock effects for the pedals it supports.
- **Firmware:** from Zoom's own updater for your pedal.
- **Handler blobs:** from the stock effects above; a tool that regenerates
  them from your own copies is still to be written. Until then, keep your
  existing copies.

## History

These files were published in earlier commits (they came with the upstream
toolchain and early research) and are still in the repository history. Removing
them from history rewrites every commit and affects everyone who has cloned or
forked it; that is a separate decision.

## Stock code inside the built effects

The linker builds each effect's knob handlers from LineSel's stock edit
handler (`build/linesel_handlers.bin`), cloned and patched for each knob, and
splices in the divide routine (`build/divf_rts.bin`). So every effect built
with it, including those in `dist/` and the NAM and cab templates, carries a few
hundred bytes of code that came from a stock Zoom effect. Untracking the blobs
does not change that. Replacing it with handlers of our own (written from the
documented ABI in [EDIT-HANDLER-ABI.md](EDIT-HANDLER-ABI.md), tested on the
pedal before any release) is the way to ship builds with no stock code in them;
see [TODO.md](../TODO.md).
