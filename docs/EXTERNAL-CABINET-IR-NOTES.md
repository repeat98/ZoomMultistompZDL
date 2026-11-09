# Zoom-ZDL-Amp-Editor cabinet / IR inspection

Inspected 2026-09-24, read-only; nothing installed or copied into dist.
NAMLite 0.12 remains unchanged.

Repository: https://github.com/Leemuzhko/Zoom-ZDL-Amp-Editor
Pinned tree: `2aa619e08625cc517c373f60cc25b8381b453bed`.
The cached GitHub page was stale: the live tree has a `zdl/` directory with
CABSIM, ENGL variants, JCM800, PLEXI, single cabinet IR variants and DUAL IR.
No editor/converter source is present in this inspected tree. The root license
is GPL-3.0; provenance of individual embedded cabinet responses is not documented
in the files inspected. No external code or coefficients were incorporated here.

## CABSIM.ZDL

Source: https://github.com/Leemuzhko/Zoom-ZDL-Amp-Editor/blob/2aa619e08625cc517c373f60cc25b8381b453bed/zdl/CABSIM.ZDL

15,692 bytes, SHA-256
`c224c2a9694b093298779da1f05a287cced80bde1ebefb26cdb9b254f3fc9dbb`.
GuitarAmp category, version 1.00, display name CAB SIM. Retains Gain, Tube,
Level, Trebl, Middl, Bass, Prese, CAB, OUT descriptor entries.

Compared byte-for-byte with local `stock_zdls/MS-50G_FDCOMBO.ZDL`:

- Same 15,360-byte ELF size and section layout.
- Same 64-byte audio entry at 0x7800, dispatching to shared `Fx_CMB_Amp`.
- Identical relocation tables and dynamic symbols.
- 592 changed bytes in `.const`, including graphics/descriptor/coefficient data.
- 11 changed bytes in the 3,104-byte executable `.text`, all within the early
  `Fx_AMP_FdCombo_tube_edit` routine; this is not entirely unchanged stock code.
- Extended 256-byte CABI header also changed.

Conclusion: a modified FD Combo wrapper/data package, not evidence of an
arbitrary WAV/IR loader. Exact sonic effect of its changed coefficients and Tube
handler was not measured. No newly embedded long IR bank was identified here.

## IRDUAL4.ZDL

Sources:
- https://github.com/Leemuzhko/Zoom-ZDL-Amp-Editor/blob/2aa619e08625cc517c373f60cc25b8381b453bed/zdl/DUAL%20IR/IRDUAL4.json
- https://github.com/Leemuzhko/Zoom-ZDL-Amp-Editor/blob/2aa619e08625cc517c373f60cc25b8381b453bed/zdl/DUAL%20IR/IRDUAL4.ZDL
- https://github.com/Leemuzhko/Zoom-ZDL-Amp-Editor/blob/2aa619e08625cc517c373f60cc25b8381b453bed/zdl/README.MD

30,690 bytes, SHA-256
`e741a4ea13334c3a90fbd9b2801a8a45304aa6024cd105810f4a081b9e61e212`.
Filter category, version 1.00. Its JSON describes a bank of four 2,048-tap
Q15 responses, float32 history, two paths with independent IR/truncation/level,
and Single/Dual mode. Metadata labels it experimental and hardware untested.

Binary observations independently consistent with that description:

- 10,784-byte executable `.text`, 17,280-byte `.const`.
- Coefficient-bank base 0x80000380; 4,096-byte response stride. Four such
  responses occupy 16,384 bytes, exactly the remainder of `.const`.
- Signed halfword coefficient loads, integer-to-float conversion and floating
  multiply/add convolution loops (e.g. code 0x09c0–0x0a68).
- Truncation loop count is 512 shifted by selector (512/1,024/2,048).
- Descriptors: IR A 0–4/default1, TRNC 0–2/default1, Level 0–150/default100,
  IR B 0–4/default1, TRNC 0–2/default1, Level 0–150/default100,
  Mode 0–1/default1. Display helpers for IR, truncation and mode are present.

This is credible evidence of embedded FIR cabinet convolution. It does not
provide a documented user-facing WAV importer or hot-loading mechanism. The
notes advise shorter truncation or Single mode for overload artifacts and state
that declared DSP cost is inaccurate. No hardware verification was performed
here, and simultaneous NAM plus IR headroom is unknown.

## Relevance and suggested next step

A separate cabinet effect could follow NAMLite when the capture excludes the
speaker. A capture already including the speaker may not need another cabinet.
This work supports exploring that path, but does not establish faithful NAM
playback or prove both effects fit together in real time.

Prefer an independently implemented mono FIR prototype with a user-supplied IR,
a conservative initial 256/512-tap length, and a simple WAV-to-ZDL conversion
workflow. At 44.1 kHz these lengths represent about 5.8/11.6 ms of IR duration,
not necessarily that much input/output latency. Measure sound and DSP headroom
alone first, then with NAMLite; extend the tail only after those checks.
Keep cabinet conversion separate from the NAM converter and retain the working
Smokey NAMLite build throughout testing. This is a proposal, not implemented work.

Reproduction: download the pinned binaries into /tmp, run
`build/disassemble_zdl.py` with the TI dis6x tool and
`build/dump_zdl_descriptor.py`, then compare ELF sections against stock FD Combo.
Beware duplicate empty `.text` sections: use the nonempty executable section
when comparing, rather than a dictionary that silently selects the final empty one.

Rechecked GitHub main on2026-09-25: tree remains
`2aa619e08625cc517c373f60cc25b8381b453bed`; no new files since this inspection.


## 2026-09-26: MS1960 in renamed Zoom-ZDL-FX repository

Pinned tree: ca54f846830b7e4d6c71b6788c8982f0d3300661.
Source: https://github.com/Leemuzhko/Zoom-ZDL-FX/tree/ca54f846830b7e4d6c71b6788c8982f0d3300661/zdl/MS1960

Downloaded and disassembled MS1960.zdl read-only; no installation, coefficient
reuse or dist changes.24678bytes, SHA256:
5130efc5bffc028c0354933811cc7903d30e2a98a0ade77537f2af5902b03457.
Metadata describes Marshall1960A/AX/AV/B. The JSON has a trailing comma
and therefore is not strict JSON. No converter or DSP source in the inspected
repository tree; it contains binaries, metadata and graphics.

Binary findings:
- Internal implementation name HYBRIDIR; displayed name MS1960.
-15104byte executable code;6520byte.const and144byte.fardata. The older
 IRDUAL4 had17280byte.const and30700-ish totalbytes (30690 exactly).
- Controls:OUT-L/OUT-R0–150; MODE0–3; IR-L/IR-R0–4; separate RESO/PRES0–60.
- At0x11cc/0x11e0, signed16-bit coefficient loads feed float FIR MACs.
 At0x13d0 onward, coefficient multiplies plus recursive state updates resemble
 cascaded biquad filters. A corresponding second path appears around0x1f84/
 0x2150. Thus a FIR plus recursive-filter hybrid is a supported inference,
 not a fully reconstructed algorithm or confirmed arbitrary-IR fidelity.
- A small state-size check uses0x5b0 (1456bytes), far below long convolution
 storage; exact state semantics were not reconstructed.

Useful leads: cabinet-specific FIR/IIR approximation, compact coefficient
storage, multiple cabinet choices, dual-path processing and user-facing EQ.
Potentially relevant to a CPU-efficient cabinet loader, not a drop-in NAM
optimization or evidence a ten-second Slö reverb can fit. A cabinet response
can be approximated by filters; a nonlinear NAM network cannot generally be
replaced by that same technique.

The author's zdl/README.MD still warns that IR overload can produce crackling
and DSP-cost reporting may be inaccurate. Its TRNC wording describes the older
IR loader; MS1960 has no TRNC descriptor, so do not assume those controls apply
to this new build. No new measured CPU figures or MS1960 hardware compatibility
claims were independently verified here.

## 2026-09-28: packaging update, unchanged DSP binary

Rechecked the live GitHub API. Current revision:
`f0acbbac7f38c0ec4517bf0f3065ac3779adf5b5` (2026-09-27).
[Exact comparison against our previous inspection](https://github.com/Leemuzhko/Zoom-ZDL-FX/compare/ca54f846830b7e4d6c71b6788c8982f0d3300661...f0acbbac7f38c0ec4517bf0f3065ac3779adf5b5)
lists only:

- Updated `zdl/MS1960/HYBRIDIR.png` thumbnail.
- Renamed `MS1960.json` to `MS1960.JSON` and removed its trailing comma,
  fixing the strict JSON syntax issue noted above.

`MS1960.zdl` is unchanged (24,678 bytes; Git blob
`f02bbdea8d03a1f8283f0289838a0c80111c2a1f`). No other files changed across
the repository in this comparison. The V30 T1/T2 variants already existed
at the previously inspected revision; they are not new in this update.
There is no new DSP implementation, converter source or performance evidence
to apply to NAMLite or our IR loader. No installation or dist changes made.

## 2026-09-29: published HYBRID-IR source and MESA test

Source: https://github.com/Leemuzhko/HYBRID-IR
Pinned revision: `be94ae58a299af50aabd97921fbd110290b554f7`.
Source reviewed/downloaded into `/tmp/hybrid-ir-review`. The published
`template_patch` path verifies the HIR3A passport hash, packs the bank, rebuilds
layout/relocations, and checks section sizes and identity conflicts.

Created `dist/IRMesa/IRMesa.zdl`, GID 2 / FXID 566, using the user's MESA WAV.
256 taps, 44.1 kHz, no minimum-phase transform or hybrid fitting, 32-sample
tail fade, peak FFT response normalized to -3 dB. Upstream supplies the neutral
RESO/PRES controls. Detailed preparation, hashes and bank layout are recorded
in `build/probes/hybrid-mesa/review.json`; testing instructions and attribution
are included with the dist package. No pedal installation performed.

All 16 upstream `test_template_packages.py` tests passed with TMPDIR set to
`/private/tmp` (the default macOS `/var` symlink is rejected by their export
path validation). Export capacity checks passed: code+constants 19,456 bytes,
below this template's 28,904-byte profile. Descriptor readback confirms name,
parameter defaults and one selectable MESA entry. This is not a hardware or
real-time performance validation.

Shared UI direction: a NAM & IR Loader with separate amp-capture and cabinet
IR tabs. Keep model conversion engines separate. Validate this test on hardware
before integrating the IR template into the loader or changing its category.
