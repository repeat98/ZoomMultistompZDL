# Installing ZDLs With Zoom Effect Manager

On an MS-70CDR you can also install them without Effect Manager: open the
[Patch Editor](https://themanro.github.io/ZoomMultistompZDL/tools/patch_editor.html),
connect, and use **Effects** (see the README).
Effects can also put back Zoom's own effects from Zoom's firmware updater,
the way Effect Manager installs them, without Effect Manager.

The release `.ZDL` files are in [../dist/](../dist/). Use
[Zoom Effect Manager](https://zoomeffectmanager.com/en/download/) 2.3.3 or
newer and point it at that folder.

## Steps

1. Connect the pedal first, then open Zoom Effect Manager.
2. Open `Settings`.
3. Choose `Read Effects from folder`.
4. Select this repo's `dist/` folder.

![Read effects from folder](images/read-effects.png)

5. In the effect source/filter area, enable `Effects from devices`.
6. Enable `From Folder`.
7. Add the desired custom effects and write them to the pedal.

![Enable From Folder](images/from-folder.png)

## Spool's new effect ID (29 October 2026)

Spool moved from effect ID 409 to 914 (version 1.02). TEcho4.ZDL in
[repeat98/ZoomMultistompZDL](https://github.com/repeat98/ZoomMultistompZDL)
used 409 too, and swapping one for the other in Effect Manager froze an
MS-70CDR at boot until its ROM was reprogrammed. Never keep two effects with
the same ID in your library or on the pedal.

If your pedal has the old Spool: remove it and write the pedal, power-cycle,
then add the new Spool.ZDL and write again. Don't swap it in one write.
Patches that used the old Spool show an empty slot; pick Spool again there.
The Patch Editor's Effects does the same in two steps: Remove, power-cycle,
then Install.

## "No data to display, check filters"

This is the most common report, and it is almost always one of the first two:

1. **The `From Folder` source is not enabled.** Choosing the folder in
   `Settings` only tells Effect Manager where to look. The browser has separate
   source checkboxes -- `Effects from devices` and `From Folder` -- and with
   neither ticked the list is empty and it says exactly this. Steps 5 and 6
   above are not optional.
2. **The pedal was connected after Effect Manager was opened.** Connect first,
   then launch it.
3. **A category filter is hiding them.** Every effect in this pack is in the
   **Delay** category. If the browser is filtered to another category they are
   there but not listed.
4. **The files are not actually ZDLs.** See below -- this bites Windows users
   in particular.

## Check that your download is real (Windows especially)

Clicking a `.ZDL` in GitHub's web interface and using *Save as* saves the HTML
page, not the file. The result has the right name and is useless. Use the
**Download raw file** button, or download the whole repository as a ZIP, or
`git clone`.

A genuine `.ZDL` from this pack:

* is between **5 KB and 23 KB** -- an HTML page is typically 100 KB or more
* begins with the bytes `00 00 00 00 53 49 5a 45` (`SIZE` at offset 4). An
  HTML page begins with `3C 21 44 4F` (`<!DO`)

On Windows, `certutil -f -encodehex Spiral.ZDL con 8 | more` shows the first
bytes; or just check the size in Explorer, which is enough to catch it.

Also make sure Explorer is not hiding extensions (`View > Show > File name
extensions`). A file saved as `Spiral.ZDL.txt` looks correct in a folder listing
with extensions hidden and will never be read.

## Notes

Back up your current effect list before writing. Current release effects target
ZDL-based MultiStomp pedals and are only hardware-tested on MS-70CDR firmware
2.10 so far.

If an effect does not appear, confirm that Zoom Effect Manager is reading the
same `dist/` folder shown in this repo and that the `From Folder` source is
enabled.

On MS-70CDR firmware 2.10, a Drive-category custom effect can flash correctly
but stay hidden in the pedal's on-device FX browser if no stock Drive effect is
installed. If `ToTape9.ZDL` writes successfully but does not appear while
scrolling effects, also install at least one stock Drive effect. With a stock
Drive effect present, the custom Drive effect has been reported visible.

## Effect Manager thumbnails

The `dist/` folder includes a matching PNG for every effect. Keep the PNG beside
its ZDL with the same basename, for example `Stasis.ZDL` and `Stasis.png`.
Restart Effect Manager after adding or changing these files; it reads the folder
at startup. Thumbnails do not require rewriting effects to the pedal.

To regenerate thumbnails from the actual embedded artwork:

```sh
python3 build/make_em_thumbnails.py
```

Icons use the bundled Effect Manager format: 128×96 RGBA with opaque black
artwork and a transparent background. Opaque RGB images can display as solid
tinted blocks. The cover inside preserves the pedal display proportions.
The PNGs affect Effect Manager
only; the ZDL already contains the pedal's own artwork. See the
[Effect Manager folder documentation](https://zoomeffectmanager.com/en/posts/reading-effects-from-folder/).
