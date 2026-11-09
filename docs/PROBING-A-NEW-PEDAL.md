# Probing a Zoom pedal this project has never seen

Everything in this repository was reverse-engineered against **one** pedal: an
MS-70CDR on firmware 2.10, device id `0x61`. The `.ZDL` container, the 146-byte
patch layout, every bit offset in the editor's tables — all of it is specific to
that machine.

The `+` models (**MS-50G+, MS-60B+, MS-70CDR+**) use a different container,
`ZD2`, so the releases in `dist/` do not load on them.

**September 14, 2026 update:** Stomphacks now documents a C-to-ZD2 pipeline and
hardware-tested custom effects on the MS-70CDR+. General feasibility is no
longer the open question for that model. See [ZD2 port notes](ZD2-PORT-NOTES.md).
The checks below preserve our earlier device-discovery work; they are not an
installation procedure or evidence of support for another model.

**One report is in.** An MS-60B+ owner ran all three checks in August 2026 and the
results are at the bottom of this page. Short version: the ZD2 container is the
same `ZDLF` family as ZDL and wraps a plain ELF, so nothing is encrypted -- but
the patch dump command is different, so the editor cannot read a `+` patch yet.

## What remains to establish

For our pack, the remaining work is adapting the ZD2 audio interface, verifying
state and delay-memory allocation, and testing each target model. PE also needs
a separate patch-protocol implementation. None of those ports has been done.

The three historical checks below concern readable effect data, MIDI identity,
and patch readback. Plain ELF and entropy observations cannot by themselves
rule out signatures or other loader checks. Stomphacks' reported successful
custom installs are stronger evidence for its tested MS-70CDR+ setup.

---

## Check 1 — Is the effect binary readable, or encrypted?

Do this one first. If a `.ZD2` is encrypted or signed, nothing else matters.

**Get a file.** `.ZD2` effects live wherever Zoom's own software keeps them on
your machine — search your drive for `*.ZD2`. Any one will do; two or three is
better, because a single file is not a sample.

**Run the inspector.** No install beyond Python 3:

```bash
python3 build/inspect_zd2.py /path/to/Effect.ZD2
```

**Read the spread, not the single number.** Real code is *uneven*: headers and
tables are low entropy, instruction streams middling. Encryption and compression
are flat and high everywhere, and that flatness is the tell.

A known-plain file — one of this repo's own ZDLs — looks like this:

```
  FOUND b'\x7fELF' at offset 76 — ELF object — same family as ZDL; disassemblable
  entropy, whole file: 5.94 bits/byte  (8.00 = indistinguishable from random)
  per-block (1024B, 10 blocks): min 1.97  max 6.54  spread 4.57
  -> UNEVEN. Typical of real code and data. Analysable.
  zero-run bytes: 18.8%  (encryption leaves almost none)
```

Encrypted or compressed data looks like this instead:

```
  entropy, whole file: 8.00 bits/byte  (8.00 = indistinguishable from random)
  per-block (1024B, 39 blocks): min 7.79  max 7.85  spread 0.06
  -> FLAT AND HIGH everywhere. Consistent with encryption or compression.
  zero-run bytes: 0.0%  (encryption leaves almost none)
```

The tool is validated against three controls: a known-plain ZDL, `/dev/urandom`,
and a gzip stream.

| Result | What it means |
|---|---|
| **UNEVEN**, ELF or other structure found | Plain code. This is the expected answer, and the encouraging one. |
| **FLAT AND HIGH**, no structure | Encrypted or compressed. Note that compression is *not* a lock — if a container tag or a `gzip` magic shows up, unpack it and inspect what is inside before concluding anything. |
| inconclusive | Try more files. |

Report the **output**, not a conclusion. The breakdown is what decides this.

---

## Check 2 — Does the pedal talk at all?

Open the patch editor:

**https://themanro.github.io/ZoomMultistompZDL/tools/patch_editor.html**

Connect the pedal over USB, put it in normal mode with Effect Manager **closed**,
and click **Connect MIDI**. Then open **Show diagnostics** and look for the
identity line in the log:

```
identity: f0 7e 00 06 02 52 61 00 00 00 32 2e 31 30 f7
                          ^^ device id      ^^^^^^^^^^^ firmware, ASCII
```

`52` is Zoom. The next byte is the device id — `61` is the MS-70CDR. A `+` model
will report something else.

**The editor is safe here.** When it sees a device id other than `0x61` it:

* adopts that id so reads are addressed correctly — otherwise the pedal ignores
  every request and the editor merely looks broken;
* switches to **read-only** and blocks every write command (`0x28`, `0x31`,
  `0x32`, `0x33`) outright.

Writes are blocked rather than warned about, because every byte offset in this
editor was mapped against one pedal and writing them elsewhere would scramble
patches on hardware nobody has mapped.

| Result | What it means |
|---|---|
| An identity reply appears | The pedal speaks the universal MIDI identity request. Note the device id and firmware. |
| Nothing | Either it does not answer identity requests, or it does not present a MIDI port at all. Both are useful facts. |

---

## Check 3 — Will it hand over a patch?

Still in the editor, click **Re-read patch**, or **Reload bank** for all 50.

> Reload bank makes the pedal cycle through every patch **out loud**. Mute your
> amp first.

If a dump comes back, the log says so and the diagnostics will contain the raw
146 bytes. **On an unmapped model that is the single most valuable thing you can
produce.** It tells us the patch protocol is shared, and the bytes themselves are
the start of mapping the layout.

Do not be discouraged if the slots decode as nonsense — the editor is applying
MS-70CDR bit tables to a pedal they were not built for. The raw bytes are the
point, not the interpretation.

| Result | What it means |
|---|---|
| A 146-byte dump | The patch protocol carries over. Editor support is plausible well before custom effects are. |
| A dump of a different length | Related protocol, different patch format. Still very useful — report the length. |
| Silence | The command differs or is gone. |

---

## Confirmed so far: MS-60B+ (device 0x6e, firmware 1.20)

First real report, August 2026. It settles the format question and reframes the
MIDI one.

**Check 1 — the ZD2 payload is not protected.** Three effects inspected, and the
result is stronger than "analysable":

```
first 32 bytes: 5a 44 4c 46 78 00 00 00 ...
FOUND b'ZDLF' at offset 0 — ZDL-family tag
FOUND b'\x7fELF' at offset 467 — ELF object
entropy, whole file: 5.28 bits/byte
per-block (1024B, 14 blocks): min 1.03  max 6.35  spread 5.32
-> UNEVEN. Typical of real code and data. Analysable.
zero-run bytes: 27.3%
```

`5a 44 4c 46` is the ASCII tag **`ZDLF`** — the same container family as the ZDL
files this repo builds — wrapping an ordinary **ELF object**. Consistent across
all three files, entropy in the 5.3 range with a wide per-block spread and around
27% zero runs. The inspected payloads are readable ELF. These observations alone do not
establish whether the loader performs signature or integrity checks.

**Check 2 — it answers, on a different device id.** `f0 7e 00 06 02 52 6e 00 27
00 31 2e 32 30 f7`: Zoom, device **0x6e**, firmware **1.20**. The editor detected
the mismatch, adopted the id so reads address correctly, and blocked writes, all
as intended.

**Check 3 — the dump command is different.** `0x29` does not return a patch. The
pedal replies with six bytes, `f0 52 00 6e 00 00 f7`, which is presumably a "no"
of some kind. So the patch protocol is NOT shared, and the editor cannot read a
`+` patch until the real command is found.

What the pedal volunteers instead is more interesting than what it refused:

| Message | Meaning |
| --- | --- |
| `f0 52 00 6e 64 26 00 00 <bank> 00 <prog> 00 f7` | current patch, as bank + program |
| `f0 52 00 6e 64 20 00 64 02 <lo> <hi> 00 00 00 f7` | unidentified, one 14-bit value that varies per patch |
| `b0 00 00`, `b0 20 <bank>`, `c0 <prog>` | bank select + program change, emitted by the pedal |

Cross-checking every program change sent against the bank/program reported back
confirms **banks of ten**: PC 37 answers bank 3 program 7, PC 40 answers bank 4
program 0. So the `+` series addresses patches as `bank * 10 + program`, and
`0x64` looks to be its notification namespace.

**Do not go hunting for the dump command by trying command bytes.** On the
MS-70CDR an unknown command byte (`0x33`) erased all fifty patches. The safe route
is to MIDI-capture Zoom's own editor for the `+` series and read the request it
sends -- the same approach that settled how ToneLib drives slots 4-6, documented
in [MIDI-PARAM-EDIT.md](MIDI-PARAM-EDIT.md).

## Reporting

Open an issue with:

1. the pedal model and firmware version,
2. `inspect_zd2.py` output for two or three effect files,
3. the editor's **Copy diag** output after connecting and attempting a read.

Raw output beats a summary. Several dead ends in this project came from someone
(usually the author) reporting a conclusion instead of the data, and the
conclusion being wrong.

## What none of this tells you

Even if all three checks come back positive, that establishes only that the
pedal is *analysable and talks*. It says nothing about whether effect binaries
can be written to it, which is the part that decides whether custom effects are
possible at all. That needs someone to look at what Zoom's own tool for the `+`
models does — and if it turns out there is no write path, the honest answer is
that this approach does not transfer.
