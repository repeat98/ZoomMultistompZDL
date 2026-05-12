# Build Context for Future Agents

Read this before changing `build/linker.py` or adding a new ZDL build path.

* The linker emits a Zoom ZDL wrapper around a TI C674x ELF shared object.
* Manual extraction from the TI PDFs lives in `docs/TI-PDF-NOTES.md`. Use that
  for ABI/register/relocation/compiler claims.
* `gid` controls both ZDL header category and SONAME prefix:
  `1=DYN`, `2=FLT`, `3=DRV`, `6=MOD`, `7=SFX`, `8=DLY`, `9=REV`.
  Mismatches can hide effects or put them in the wrong category.
* `Dll_<Name>` is a patched verbatim NoiseGate DLL body. Keep it unless a
  hardware test proves a replacement is safe.
* The DLL-declared descriptor count must be `2 + len(params)`. This fixed the
  3+ parameter edit-mode rendering bug.
* `effectTypeImageInfo` is always 212 bytes and only has three visible knob
  coordinate slots. The firmware paginates 4-9 parameters from the descriptor.
* The generated `.fardata` image must stay small and must have `memsz == filesz`.
  Big writable state has frozen hardware.
* Compile plugin C with `--mem_model:data=far` so the compiler does not emit
  B14/SBR-relative accesses.
* `B14` is the C6000 data page pointer. The host does not establish a data page
  for our custom object before calling `.audio`, so reject `R_C6000_SBR_*` and
  `R_C6000_SBR_GOT_*` relocations from plugin objects.
* Supported object relocations are intentionally narrow: absolute address forms
  and known PC-relative branches. Do not add GOT/DSBT/TLS/C++ exception
  machinery without a dedicated hardware experiment.
* `__c6xabi_divf` is bundled. Other RTS helpers are not automatically safe.
  Pay special attention to `__c6xabi_push_rts`, `__c6xabi_pop_rts`, integer
  division/remainder helpers, double helpers, and conversion helpers.
* High `--opt_for_space` can cause RTS call stubs/push-pop helpers. Several
  build scripts avoid it on purpose.
* When a new effect freezes on load, verify with `audio_nop: true` first. If
  NOP loads, the linker structure is probably fine and the DSP is suspect.

Long-form details live in `build/ABI.md`, `docs/SAFE-DSP-RULES.md`, and
`docs/TI-PDF-NOTES.md`.
