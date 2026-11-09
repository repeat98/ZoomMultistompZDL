# How Zoom Effect Manager installs effects (MS-70CDR 2.10)

Observed on 2026-10-23 by recording Effect Manager 2 talking to the owner's
MS-70CDR (firmware 2.10) with MIDI Monitor's spy driver on macOS: one full
cycle of read, update mode, flash and reboot, 3,022 messages. This file
records the message structure and the file system layout only. No Zoom code,
firmware or file contents are reproduced here; keep the capture itself local.

Nothing here has been sent to a pedal by our own tools yet. Treat every write
command below as dangerous until a test tool reproduces Effect Manager's
bytes exactly.

All messages are SysEx `F0 52 00 <device id> <command> … F7` (MS-70CDR
device id `0x61`). Numbers inside messages are 7-bit groups, least
significant first.

## 1. Normal mode: what is installed

1. Identity request (`F0 7E 00 06 01 F7`) twice; the reply carries the
   firmware version as text ("2.10").
2. `01`: status. The pedal answers `00 0B` in normal mode.
3. `50`: editor mode on. `33`: current bank and program (the pedal answers
   with CC0, CC32 and a Program Change).
4. Program Change to patch 50, then about 58 rounds of:
   - write a scratch patch named "Temp ZEM" into the edit buffer
     (`28` + the usual 146-byte patch), with several effect ids in its slots;
   - read it back (`29` → `28`).
   Slots whose effect is not installed presumably come back empty, so a
   round answers "which of these ids are installed". This is how Effect
   Manager learns the pedal's effect list without any file command.
5. Program Change back to the original patch, `51` (editor mode off).

The scratch patch is never stored, but it does sit in patch 50's edit
buffer: with AUTO SAVE on, check that it cannot end up saved there.

## 2. Update mode

The owner powers the pedal on in firmware update mode. Effect Manager only
polls: identity every ~1.5 s (the version text now reads "1.1…", the boot
loader) and `01`, which now answers `00 00`. No command switches modes.

## 3. Flash

| Command | Layout | Meaning |
| --- | --- | --- |
| `0A` | address (5) + length (5) | Erase a flash range. Answer `00 00`. The 2.7 MB erase took about 10 s. |
| `02` | address (5) + length (2) + data + CRC32 (5) | Write one block. Data is 2,048 bytes packed 8-into-7 (high bits first), CRC32 of the unpacked block XOR `0xFFFFFFFF`, as in zoom-zt2. Answer `00 00` per block. |
| `04` | – | Finish. The pedal reboots; Effect Manager polls identity until it is back. |

Order seen: erase and write `0x3B0000`–`0x3B7000` (28 KB), then erase
`0x0F0000`–`0x392000` and write it from the start, 1,362 blocks in all,
every CRC correct. The effect file system starts at flash address
`0x0F0000`; offsets below are relative to it. Its size matches the updater's
`FS.bin`, which holds the same file system as shipped.

So installing one effect rewrites the whole effect file system. There is no
per-file transfer on this pedal.

## 4. File system layout

- Offset `0x0000`: a short header, then erased space.
- Offset `0x3000`: the directory, 32-byte entries until the first `0xFF`
  name byte:
  - bytes 8-9: first cluster (u16, little-endian);
  - byte 10: `01` (used);
  - bytes 12-15: file size (u32, little-endian);
  - bytes 16-27: 8.3 name, padded with `00`/`FF`.
  The first entries are `FLST_SEQ.ZDT` (the effect list) and `CMN_DRV.ZDL`,
  then the effects.
- Data clusters of 4,096 bytes from offset `0xA000` (cluster *n* at
  `0xA000 + n × 0x1000`). Each starts with a 6-byte header: previous
  cluster, next cluster (`0xFFFF` = none) and bytes used (u16 each), then up
  to 4,090 bytes of file data.

Checked by rebuilding Howl and Dustbox from the written image: both match
their `dist/` files byte for byte.

Effect Manager writes a fresh, compact image: the header, the directory
packed from `0x3000`, and the files one after another from cluster 1 in
directory order, every unused byte `0xFF`. (Zoom's shipped `FS.bin` is laid
out differently, with gaps; an image does not have to look like it.)

### `FLST_SEQ.ZDT`, the effect list

Sections, one per effect group: `>>>` `00`, the group id (`00`, `01`, …,
`0C`), eight `00` bytes, then one 13-byte record per effect (the file name
padded with `00` to 12 bytes, then one byte, `00` in every record seen), and
`<<<` `00` to close the section. Groups seen: 0, 1, 2, 3, 6, 7, 8, 9, 12.
The rest of the 4,108-byte file is `00`. The record order is the order the
pedal lists effects in.

Order rules, from a second capture (2026-10-23) that added two stock effects
and removed one:

- **Effect list:** within a group, Zoom's effects keep a fixed master order,
  and a newly added one is inserted at its place in that order, not at the
  end. Custom effects (ours, Matujuice) follow the stock ones in their group.
- **Directory:** `FLST_SEQ.ZDT`, `CMN_DRV.ZDL`, then Zoom's effects in the
  same master order but grouped by the menu category (a bass drive sits with
  the drives), then all custom effects together at the end.
- The per-record byte was `00` in every record of both captures.

The master order comes from Effect Manager's own effect database, not from
the pedal. That database (its effect library) holds many more effects than
any one pedal has installed, for every pedal it supports, so the captures
show only the selected ones. A complete master order, and the source of
each library effect, needs that library or the updaters of every pedal it
draws on (MS-50G, MS-60B, MS-70CDR, G1on/G1Xon, B1on/B1Xon).

### What an installer needs

Every install rewrites the whole file system, so an installer must have
**every** file that stays on the pedal, Zoom's stock effects and `CMN_DRV.ZDL`
included. Effect Manager does not read them back from the pedal, but the
pedal can give them back itself (section 5). Zoom's files cannot be shipped
with our tools.

They can come from Zoom's own updaters, which are free downloads on each
pedal's support page. An updater's `FS.bin` holds that pedal's stock
effects. It is laid out like an Effect Manager image but keeps several
directory copies; an entry whose byte 11 is `00` is superseded
(`zoom_fs.py stock` handles both).

Effect Manager installs the same effects with their ELF debug sections
removed. TI's `strip6x` (no options) reproduces that exactly; the ZDL's size
field at `0x10` is then set to the new ELF length. Checked on the second
capture: 99 of the 104 stock effects found in the MS-70CDR 2.10 updater
match byte for byte. The other 5 are newer builds (1.01) that Effect Manager
takes from the B1Xon. It picks each effect from the pedal with the newest
build (the amp effects and `CMN_DRV.ZDL` come from the G1Xon/MS-50G).

Rebuilding the whole second image from independent sources (the MS-70CDR
updater, stripped; the owner's local stock copies; our `dist/`), with only
`FLST_SEQ.ZDT` and four stock effects taken from the capture because no local
source had them, gives Effect Manager's image byte for byte.

## 5. The pedal's own file commands (normal mode)

Effect Manager never uses them, but the MS-70CDR 2.10 answers the file
commands that [zoom-zt2](https://github.com/mungewell/zoom-zt2) uses on the
ZD2 pedals, with device id `0x61` in place of the G1Four's `0x6E`. Checked
read-only on the owner's pedal, 23 October 2026, with `tools/file_probe.html`:

| Command | Reply |
| --- | --- |
| `60 29 …` disk usage | Total and free bytes (7-bit groups): about 2.86 MB, 139 KB free |
| `60 25 00 00 "*" 00`, then `60 26 …` | One file per reply (`60 04 25 …`): name at byte 14, size after it; all 162 files, in directory order; `60 03 7A 7F …` at the end |
| `60 20 02` + 9 × `00` + name + `00` | Opens a file for reading |
| `60 05 00`, `60 22 14 2F 60 00 0C 00 04 00 00 00`, `60 05 00` | One 512-byte block, in the reply to the second `60 05 00` (`60 04 22 01 …`: length, packed data, CRC32); length 0 at the end |
| `60 21 40 00 00 00 00`, `60 09` | Close |

`FLST_SEQ.ZDT` read this way (9 blocks, every CRC correct) is byte for byte
the file Effect Manager wrote in the second capture. So a complete backup of
the pedal's files over USB is possible, and stock effects can come from the
pedal itself instead of the updaters.

Writing and deleting single files works too (owner's pedal, 23 October 2026,
after a verified backup), with zoom-zt2's sequence:

| Step | Messages |
| --- | --- |
| Check | `60 25 00 00` + name + `00`, `60 05 00`, `60 27` |
| Write | `60 24` + name + `00` (delete), `60 20 01` + 9 × `00` + name + `00`, `60 05 00`; per block of up to 512 bytes `60 23 40 00 00 00 00`, length (2), `00 00 00`, packed data, CRC32 (5), then `60 05 00` |
| Delete | check, then `60 24` + name + `00` |
| Close | `60 21 40 00 00 00 00`, `60 09` |

A 700-byte `TEST.TXT` (two blocks) was written, read back identical, listed
(163 files), still there after a power cycle with the pedal booting and
playing normally, then deleted (162 files again). So a per-effect install
needs neither update mode nor a full reflash.

Effects, same day, same pedal, all with `tools/file_probe.html`:

- **Replace:** writing another build over an installed effect's file (same
  name and effect ID; the effect list unchanged) works. Loop 0.03 -> 0.02 ->
  0.03, each build running after a power cycle.
- **Add:** write the new `.ZDL`, then `FLST_SEQ.ZDT` with one more 13-byte
  record at the end of the effect's group (the file stays 4,108 bytes; the
  zero padding at its end shrinks). After a power cycle the pedal listed the
  test effect (a copy of Ring with its own effect ID) after Ring and loaded
  it. Its live screen stayed on the cover, as expected: Ring's code looks for
  its slot by the effect ID written in its C source, and the copy only had a
  new ID in its header.
- **Remove:** write `FLST_SEQ.ZDT` without the record, then delete the file.

Write the effect file before the list, and the list back without the record
before deleting the file, so the list never names a missing file. Read back
every write. A record must not be added twice.

## Offline builder

`tools/zoom_fs.py` reads an image (`list`, `extract`), an updater (`stock`, with `--strip`), and builds one from a
folder of files and an `order.txt` (`build`). `check` extracts an image and
rebuilds it: on the captured Effect Manager image (161 files) the rebuild is
identical byte for byte. It does not generate `FLST_SEQ.ZDT` yet, and it never
talks to a pedal.

## What this means for installing from the browser

The transfer is simple. The work and the risk are in building the image:
the directory, the cluster chains and `FLST_SEQ.ZDT` have to be right, and
a bad image or an interrupted flash leaves the pedal to be recovered with
Zoom's updater. Before any write:

1. A builder that takes the pedal's effect list and produces an image, and
   reproduces Effect Manager's image byte for byte from the same inputs.
2. The normal-mode read (section 1) as a read-only step in the Patch Editor.
3. Only then a write, on the owner's pedal, with the stock updater ready.

With the file commands (section 5) the order is: a full backup of the pedal's
files, verified by rebuilding Effect Manager's image from it; a write test on
a harmless new file (not an effect, not in the effect list), read back and
deleted (done, it works); then one of our own effects.
