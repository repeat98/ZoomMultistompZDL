# Release initialization rollout and follow-up audit

## Scope

Corrected PC-relative initialization is enabled explicitly in the 22 release
build scripts. Diagnostics keep their existing configuration. Rooms also supports
`--no-materialize-init` for comparison builds. MatProb and Rooms are owner-tested
on hardware, in all slots and across patch changes/power cycles, with PE
disconnected. The remaining release effects require listening checks.

## Fix pass — 2026-09-10

The four findings below are the original audit evidence; all four now have code
fixes and regression coverage. Parameter replay remains for older installed builds.

- Valid zero is retained by shared normalization. Galactic, Oxide and Spool use
  the normalized handler contract without guessing an old x7 range. Howl and
  Dustbox seed accepted controls from loaded parameters before retaining their
  existing refocus latch. Negative/nonfinite input falls back safely.
- PE UI MIDI operations have exclusive ownership through their reads and paced
  writes. Competing actions are rejected, busy timeouts throw, and each dump owns
  its timer. Program changes cancel pending reads; Apply checks patch generation.
- Apply merges only dirty fields into a fresh dump, preserves the live name and
  untouched fields, and clears only read-back-confirmed revisions. Failed reads
  and mismatches retain edits. MIDI send failures propagate instead of retrying
  immediately outside the pacing schedule.
- Linker errors on unresolved included references and unsupported relocations.
  Tests compile a TI object with a missing external, and corrupt a relocation in
  another fixture; neither produces a ZDL. Unused undefined symbols remain allowed.

Validation: all 22 release effects rebuilt; 108 init calls and release metadata
verified; nine Python tests and nine PE Node tests pass; inline JavaScript syntax
and whitespace checks pass. Updated binary hashes are in RELEASE-INIT-VERIFICATION.json.

**Hardware: confirmed 2026-09-10.** The owner reports the rebuilt pack working on
the project's MS-70CDR ("everything works good now"), after the earlier MatProb
and Rooms confirmations of the init fix itself. This is a general owner report of
the pack in use, not a recorded per-effect matrix — individual effects have not
each been logged against a control-by-control checklist, and the Oxide/Spool
voicing changes in TAPE-VOICING-PASS.md are a matter of taste rather than pass/fail.

## Patch Editor UI audit

Fixed: Apply/Store wording; Store surfaced beside Apply; disconnected/busy action
states; status text; import label; accessible effect selectors and on/off buttons;
keyboard knobs (arrows, Shift steps, Home/End) and keyboard pedal patch selection;
focus outlines; duplicate probe option group; text-safe diagnostic logging; rejection
of mismatched-device imports when connected. Paste now uses a labeled dialog.

Browser QA used an offline Rooms fixture: import rendered all six slots, Mix
Home/End/ArrowLeft read 0/100/99, focus and layouts were visually checked, and
pedal write controls stayed disabled. No MIDI device was connected or written.

Remaining validation/limitations:

- Run connected Chrome/Edge tests for rapid patch selection, Apply, Store and
  unplug/reconnect. The available embedded browser cannot exercise Web MIDI hardware.
- Rename/destructive workflows still use browser-native prompt/confirm dialogs;
  embedded-browser support differs. Paste no longer has that dependency.
- Desktop layout was inspected; small-screen and screen-reader end-to-end testing
  remains. Drag reorder still has no keyboard equivalent for effect slots.
- Zoom dumps have no request ID. Ownership/generation checks plus a 200 ms timeout
  quarantine prevent local request theft; an arbitrarily late untagged hardware
  reply cannot be conclusively identified. Slow-device behavior needs hardware QA.


## Original findings (fixed by the pass above)

### P1: zero knob positions fall back to defaults

`src/airwindows/common/zoom_params.h:zoom_param_norm01` returns the fallback for
raw <= 0.0001. Rooms uses this for Mix with default 0.5. A host-compiled test of
the actual header returns 0.5 for raw zero, versus 0.01 for raw 0.01. Thus the
zero endpoint jumps to the default rather than reaching full dry. This survived
MatProb testing because its Gain fallback is also zero. Oxide independently has
a similar missing-value macro; effects with parameter caches need individual
review, not a blind global replacement.

Proposed: distinguish valid zero from uninitialized/invalid data, now that init
materializes saved values; review each effect's cache and fallback contract.
Verify zero, small nonzero, midpoint and maximum for each control. Handle
nonfinite values explicitly. This was not fixed in the initial audit pack; see the fix pass above.

### P1: overlapping PE operations can steal or erase pending reads

`waitIdle` returns after its timeout even while busy or syncing remains true.
The patch-row click handler then changes programs and calls `reread`, without
acquiring busy itself. `awaitDump` has one global pending request and overwrites
it; the old timer unconditionally sets pendingDump=null. Using the actual
functions in a Node VM reproduced both: waitIdle returns while busy=true, and
an older timeout erases a newer request. This can misassociate patch data or
cause timeouts during rapid clicks or a slow bank operation.

Proposed: serialize MIDI transactions with a real ownership/queue mechanism,
reject/cancel timed-out acquisition, and bind responses/timeouts to the current
request and patch generation. Test rapid selection and bank-read overlap with
mock MIDI before hardware testing.

### P2: Apply retains stale dirty fields and always overwrites the name

`applyToPedal` reads the live patch but overlays every accumulated dirty field,
then always assigns `live.name=patch.name`. Dirty fields intentionally remain
set after success, under a comment about a PC-led reload, although the current
implementation calls readCurrent with no PC. If a previously edited field is
subsequently changed on the pedal, applying another field restores PE's old
value; a pedal-side rename can also be lost. This is a source-supported scenario,
not a new hardware reproduction.

Proposed: clear only successfully applied edits after verification, track name
edits explicitly, and preserve edits made during an in-flight transaction.
Coordinate with the transaction fix above.

### P1 build safety gap: unresolved symbols and relocations only warn

`build/linker.py` logs unresolved externals, skips their relocations, and also
skips unknown relocation types. It can still write a ZDL and return success.
The audited release build's warning scan is recorded separately; this finding
concerns accepting a future broken object, not proof of a broken current effect.

Proposed: fail on unresolved relocations in included executable sections and
unsupported relocation types, with a deliberately malformed object regression
case. Avoid rejecting harmless unused undefined symbols solely by name.

## Verification commands

- `python3 -B build_all.py`
- `python3 -B -m unittest discover -s build/tests -v`
- `node --test tools/tests/patch_editor.test.cjs`
- `python3 -B build/verify_release_init.py`
- `git diff --check`

The release verifier compares each binary's complete init body with descriptor
handler targets, checks calls at multiple text bases and handler prologues,
compares parameter metadata/IDs with manifests and the editor JSON database, and
rejects extra or missing release files. Results and hashes are recorded in
`docs/RELEASE-INIT-VERIFICATION.json` after the build completes.
