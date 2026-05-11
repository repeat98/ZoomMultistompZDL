# Draft email to Alexander (Zoom Firmware Editor author)

**Subject:** MS-70CDR ZDL — 3-param effect rendering bug; need a tip

Hi Alexander,

Big admirer of Zoom Firmware Editor — it's the single most useful tool the
Zoom modding community has. Thank you for keeping it maintained.

I'm building an open-source toolchain that compiles plain C source
files into loadable `.ZDL` effects for the MS-70CDR
(`https://github.com/repeat98/ZoomMultistompZDL`). The pipeline is:

```
cl6x (TI C6000 v8.5) → .obj → custom static linker → .ZDL
```

1- and 2-parameter plugins from this linker boot cleanly and the knobs
actually modulate audio (`GAIN`, `PurestDrive`, `BitCrush`, an
earlier 2-knob `TapeHack`). However, **3-parameter plugins from the
same linker silently fall back to a 2-knob render** as soon as the user
enters edit mode — the 3rd descriptor entry is dropped from the UI even
though the `SonicStomp` descriptor declares it correctly and
`effectTypeImageInfo.nknobs = 3`. The icon preview shows 3 knob graphics;
only 2 are tweakable; no pagination indicator appears.

A renamed clone of stock `MS-70CDR_EXCITER.ZDL` shows 3 knobs on the
same firmware version (2.10), and stock `MS-70CDR_AIR.ZDL` renders its
6 paginated params correctly. So the pedal + firmware can clearly do
3+ knobs; my linker output for exactly-3 params has *something*
malformed that I can't find.

**Hardware tests I've already eliminated as the cause** (each flashed
in isolation):

* Edit handlers (AIR `mix_edit` blob vs `NOP_RETURN`).
* Last-entry `pedal_flags` = `0x04` vs `0x14` (with and without
  matching `pedal_max = max_val`).
* Knob xy positions — tried multiple layouts including verbatim Exciter
  (`(31,13)/(54,13)/(77,13)`) and AIR (`(21,36)/(45,36)/(69,36)`).
* `.dynsym` ordering: STB_LOCAL syms before STB_GLOBAL, with
  `.dynsym sh_info = first_global_idx` (= ELF spec-correct, matches
  every stock effect).
* SPRAB89B §14.4.3 fixes: `st_other = STV_HIDDEN` for locals,
  `STV_PROTECTED` for `Dll_<Name>`; plus a `.c6xabi.attributes`
  section (62 bytes spliced verbatim from Exciter).
* `effectTypeImageInfo +0x18` = 32 (Exciter/OptComp pattern) instead
  of 28 (LineSel pattern). Bytes match stock 3-param effects exactly.

**Firmware RE in progress.** I've parsed the TIPA wrapper around
`Main.bin` and produced clean compact-instruction disassembly using a
hand-crafted ELF wrapper that includes `.c6xabi.attributes` +
`.TI.section.flags` extracted from a fresh `cl6x` output. ~64K
instructions decode cleanly. From that, I've located:

* `0xc00bb600` — a multipurpose descriptor iterator (7 callers, varied
  `arg2` values 1/0/-1).
* `0xc00b056c` — `get_entry(slot_idx, entry_idx)` helper; returns
  `globals[0xc0064e04 + slot_idx*28] + entry_idx*48`.
* `0xc00b05cc` — `effect_type_code(slot_idx)` table lookup
  (`globals[0xc0064ec0 + slot_idx*4]`).
* `0xc00bd000` — per-entry debug-print function, which reveals the
  **runtime entry struct is at least 0x48 bytes** (not 0x30 like
  on-disk SonicStomp entries). The firmware re-packs each on-disk
  entry into a bigger runtime form; the extra 6 words (`+0x30..+0x44`)
  come from somewhere I haven't located.

My current best guess is that the 3-knob fallback is gated on a field
that lives in those extra runtime-only words, but I haven't been able
to find the converter function that fills them.

**What I'd love your input on, if you have a moment** (any one of
these would unblock months of work):

1. Do you happen to know what field in the descriptor or imageInfo
   gates the 3rd knob's visibility on MS-70CDR? Specifically — is
   there a value that distinguishes "3-knob single-page" from
   "downgrade to 2 knobs" that isn't `pedal_flags` / `nknobs`?
2. Have you ever RE'd the firmware's descriptor-parse function (the
   one that runs right after `Dll_<Name>` returns and converts the
   on-disk 0x30-byte entries into the firmware's larger runtime
   struct)?
3. Is there a community resource on the C6000-EABI runtime loader
   semantics that I might have missed? SPRAB89B is great for the
   static ELF side but light on Zoom's specific dynamic loader.

No pressure — I know you're busy. Even pointing me at a relevant doc
or grep target would be enormously useful. Investigation notes are
in `docs/3-PARAM-LINKER-BUG.md` in the repo above, and I'm happy to
share a stripped-down test ZDL that reproduces the failure.

Thanks for everything you've contributed to the scene.

— Jannik
