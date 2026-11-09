# Patch Editor UI refresh — 2026-09-10f

The main toolbar now contains Connect, Apply changes, Save to pedal, Library,
and Settings. Patch name/number, connection state and an edited-state indicator
sit beside them. The six slots are the main workspace; offline users see an
explanation of how to start.

Library is a modal side drawer with Pedal memory and My Library tabs. Arrow keys
switch tabs; dragging over a tab reveals its drop targets. Import/export and
copy/paste live in Share a patch. Pedal memory and browser storage remain labeled.

Settings groups Appearance, MIDI controller, Advanced and Diagnostics. Existing
LCD/P4/P3 skins are preserved. Bank backup/restore sits under Advanced. Diagnostic
probes are hidden from the effect catalogue by default, with an explicit checkbox
to reveal them; already-selected probes remain visible. Empty slots say Add effect,
and slot switches have visible On/Off text.

Existing control elements and MIDI handlers are retained when moved into drawers.
Native dialogs provide modal focus, Escape dismissal and focus return. Notices
appear inside an open drawer. Save confirmation text is shorter and uses the new
label; a failed reload no longer claims a confirmed save.

Checked in the local browser: clean start, Settings groups, amber skin, Library
keyboard tabs, paste into Rooms, knob Home endpoint and focus, loaded-slot layout.
Eight MIDI regression tests, inline script syntax, release metadata consistency,
and whitespace checks pass. No pedal connected during this UI pass. Small-screen
CSS is included; physical mobile and assistive-technology validation remain.

## 2026-09-10g: bottom notifications

Replaced the red, stacking top banners with one neutral, theme-aware bottom
status strip. It retains the latest notice until replaced or cleared; history
remains in Diagnostics. Reserved bottom spacing keeps controls clear. The strip
follows open modal drawers so it remains readable and dismissible there too.
Browser checked invalid-import notice, opening Settings, clearing the notice and
closing Settings. Eight MIDI regression tests and script syntax checks pass.

## Performance controls

Added grouped Bypass / Tuner, Resume effects, and All slots off toolbar buttons.
Tuner uses original MS-70CDR CC74 (127 on / 0 off), as documented in
https://github.com/g200kg/zoom-ms-utility/blob/master/midimessage.md .
The pedal's BYPASS/MUTE TUNER setting determines output; PE does not overwrite it.
Buttons report commands sent, not unverified hardware state. All slots off reads
fresh data, changes only on/off fields, verifies the result, and retains unrelated
local edits. No flash store. Explicit Stasis holds remain a documented exception;
use Capture=1 to release them. Offline/unsupported/busy controls are disabled.
15 Node tests pass, and controls render in the offline browser. Hardware pending.

### Slots 4–6 Apply feedback

Suppress on/off echoes only for the transient slot bounce owned by Apply; these
previously changed the displayed slot state and rebuilt every knob. Real on/off
messages outside the transaction still update the UI. Cancel a queued Apply when
starting another drag, so the earlier gesture cannot apply halfway through it.
Labels now say "Apply slots 4–6 after editing" and acknowledge the brief audio
dip. The measured late-slot fallback is retained; seamless late-slot live editing
is not established by the init fix. 16 Node tests pass. Hardware retest pending.

### Automatic slot updates and stable controls

Removed the user-facing late-slot Apply option and per-slot transport labels;
the proven fallback always runs automatically. Busy transactions keep disabled
controls at stable opacity, with a wait cursor and existing operation text.
On/off changes now update the existing slot label/toggle/class instead of
rebuilding six slots; toggle callbacks read current state rather than a stale
render-time value. Hardware echoes use the same in-place update.
17 Node tests pass and the offline page loads. This does not remove the audible
bypass gap or establish live 0x31 support in slots 4–6. The init-materialization
fix and live firmware update routing remain separate investigations.
