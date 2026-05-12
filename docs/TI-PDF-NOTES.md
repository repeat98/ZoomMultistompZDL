# TI PDF Notes for ZDL Work

Source PDFs:

* `docs/sprab89b.pdf` - C6000 Embedded Application Binary Interface.
* `docs/sprui03f.pdf` - TMS320C6000 Assembly Language Tools v8.5.x.
* `docs/sprui04g.pdf` - TMS320C6000 Optimizing C/C++ Compiler v8.5.x.

This is a practical extraction, not a replacement for the manuals. It records
the parts that explain current linker/DSP rules.

## Calling Convention

From `sprab89b`, Section 3:

* `B15` is the stack pointer. It must remain 8-byte aligned.
* `B14` is the data page pointer, also called `DP`.
* `B3` is the return address.
* First arguments are assigned as:
  `A4, B4, A6, B6, A8, B8, A10, B10, A12, B12`.
* Return values are in `A4`, or `A5:A4` for 64-bit values.
* Callee-saved registers are `A10-A15` and `B10-B15`. This includes `B14`
  and `B15`.
* All other registers are caller-saved.
* `AMR` circular-addressing bits must be clear at function boundaries.

ZDL consequence: C functions compiled by TI will respect this ABI, but
handwritten or cloned handler code must preserve callee-saved registers and
return through `B3`. Any code that assumes `B14` points at our data is unsafe
unless we set it ourselves, and we currently do not.

## Data Addressing and B14

From `sprui04g`, Section 8.1.4:

* Default C6000 data model is `far_aggregates`: arrays/structs/classes are far,
  scalar globals/statics are near.
* Near data is placed in `.bss` and accessed relative to `DP`/`B14`.
* Far data is accessed with absolute addressing.
* `--mem_model:data=far` makes data accesses default to far.
* `__near` means "use DP-relative addressing"; `__far` means "do not use DP".
* `DATA_SECTION` makes an object far and needs `extern __far` declarations if
  referenced across files.

ZDL consequence: always compile plugin DSP C with `--mem_model:data=far`.
Reject `R_C6000_SBR_*` object relocations from plugin `.audio` code, because
those are DP/B14-relative forms. The Zoom host does not set `B14` for our
module before calling `.audio`.

## Sections and Zero Fill

From `sprui03f`, Section 2, and `sprui04g`, Sections 6/8:

* `.text` and `.sect` are initialized sections: bytes exist in the object file.
* `.bss` and `.usect` reserve uninitialized memory and do not carry load data.
* Uninitialized global/static variables are emitted as common symbols by
  default unless `--common=off` is used.
* The compiler/runtime can expect zero-initialization support for uninitialized
  variables.

ZDL consequence: avoid `.bss`, `.usect`, common symbols, and uninitialized
static storage. Our ZDL loader path is not a normal C runtime startup. Use
small initialized data only, and keep writable `.fardata` small with
`memsz == filesz`.

From `sprui04g`, Section 8.9:

* Normal C startup initializes the stack, zeroes uninitialized globals/statics,
  processes C autoinitialization records, and runs C++ constructors.
* Under `--ram_model`, a loader must handle data and zero initialization.
* Heap allocation uses `.sysmem` and linker-provided heap sizing.

ZDL consequence: a plugin audio callback should not rely on C runtime startup
unless we implement or prove equivalent loader behavior. This rules out
ordinary `.bss`/`.far` state, `.cinit` tables, constructors, and heap-based
state for release builds.

## Runtime Helper Functions

From `sprui04g`, Section 8.8:

The compiler inserts `__c6xabi_*` RTS helper calls for operations the
instruction set does not directly cover. Examples include:

* `__c6xabi_divf`, `__c6xabi_divd`
* `__c6xabi_divi`, `__c6xabi_divu`, remainder helpers
* double/float conversion helpers
* long-long arithmetic helpers

From `sprab89b`, helper-function API:

* `__c6xabi_push_rts` / `__c6xabi_pop_rts` are emitted under code-size
  optimization to save/restore callee-saved registers via RTS routines.
* `__c6xabi_call_stub` can be used to save selected caller-saved registers
  around calls.

ZDL consequence: inspect external symbols after every build. `__c6xabi_divf`
is currently bundled by this repo. Other helpers are not automatically safe.
Avoid `double`, integer division, modulo, long long, implicit conversions, and
high `--opt_for_space` unless the exact helper is bundled and tested. Consider
`--disable_push_pop` if a build starts emitting push/pop RTS helpers.

## Relocations

From `sprab89b`, Section 13.5:

* `R_C6000_ABS32`, `R_C6000_ABS_L16`, `R_C6000_ABS_H16` encode absolute
  addresses and are the forms this linker knows how to patch.
* `R_C6000_PCR_S21` is a PC-relative branch/call relocation.
* `R_C6000_SBR_*` are DP/B14-relative relocations.
* `R_C6000_SBR_GOT_*` are GOT forms, also DP-relative.
* `R_C6000_ABS_H16` and other H16 relocations are Rela-only because the high
  bits depend on carry from the low part.

ZDL consequence: `ABS*` and known `PCR_S21` relocations are expected. `SBR`,
`GOT`, `DSBT`, TLS, exception, or C++ relocations should be treated as a build
failure for custom DSP objects unless the linker explicitly supports them and
hardware testing proves them safe.

## Dynamic Linking and Visibility

From `sprab89b`, Sections 6/14:

* C6000 EABI supports ELF shared objects and dynamic relocations.
* The DSBT model uses `B14`/`DP` and a data segment base table.
* Symbol visibility controls preemptability:
  `STV_HIDDEN`/`STV_INTERNAL` are not exported,
  `STV_PROTECTED` is exported but not preemptable,
  `STV_DEFAULT` is exported and preemptable.

ZDL consequence: our linker is deliberately narrow. It emits the symbols the
Zoom loader needs, keeps most local symbols hidden/protected, and avoids DSBT
machinery. Do not introduce normal shared-library assumptions such as GOT,
PLT, imported data, or C++ runtime features.

## Compact Instructions and Attributes

From `sprab89b`, Sections 13/17:

* C64x+ and later support compact instruction encoding.
* Build attributes encode target/ABI properties such as ISA.
* `.TI.section.flags` and `.c6xabi.attributes` matter to tools that decode or
  validate C6000 ELF objects.

ZDL consequence: preserve the bundled attribute/section-flag blobs in the
linker output. Firmware disassembly also needs these to decode compact
instructions accurately.
