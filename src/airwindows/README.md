# Airwindows Port Layout

Before adding or deepening a port, read
[AGENT_CONTEXT.md](AGENT_CONTEXT.md) and
[../../docs/SAFE-DSP-RULES.md](../../docs/SAFE-DSP-RULES.md). The short
version: exact source parameter metadata is good; full desktop DSP with large
state is not automatically safe on the pedal.

also [AIRWINDOWS-EXACT-PORTS.md]

For effects marketed as Airwindows ports, also read
[../../docs/AIRWINDOWS-EXACT-PORTS.md](../../docs/AIRWINDOWS-EXACT-PORTS.md).
If the DSP is an approximation or an ABI probe, say that plainly in the
manifest and comments. `StChorus` is now the first hardware-confirmed
`ctx[3]`-backed `StereoChorus` port; keep documenting remaining numerical
differences before calling it bit-for-bit equivalent.

Hardware-only ABI probes live in [../hardware_probes/](../hardware_probes/),
not in this Airwindows source tree. Their findings belong in
[../../docs/STATE-ABI-PROGRESS.md](../../docs/STATE-ABI-PROGRESS.md) before
they are used to justify a stateful port.

Each effect directory is meant to be buildable on its own and through
`python3 build_all.py`.

Required files:

- `manifest.json`: effect name, category, fxid, version, and 1-9 params.
- `build.py`: compiles the C file with TI `cl6x`, then calls
  `build/linker.py`.
- `<effect>.c`: exports `Fx_FLT_<Name>` in `.audio`.

Manifest params can describe more than plain `0..100` knobs:

```json
{
  "name": "Mode",
  "type": "switch",
  "max": 1,
  "default": 0,
  "labels": ["Off", "On"],
  "audio_default": 0
}
```

For continuous controls, keep UI range and DSP range separate:

```json
{
  "name": "Freq",
  "type": "knob",
  "min": 0,
  "max": 100,
  "default": 50,
  "scale": "hz",
  "unit": "Hz",
  "audio_min": 25.0,
  "audio_max": 200.0,
  "audio_default": 0.5
}
```

The linker writes descriptor fields from `min/max/default/flags`. Build
scripts can call `write_param_header(...)` from
`common/manifest_params.py` so DSP code gets generated slot/default/range
defines from the same manifest.

For ports with more than two controls, include
`../common/zoom_edit_handlers.h` and define one `ZOOM_EDIT_HANDLER` per
param:

```c
#include "../common/zoom_edit_handlers.h"

ZOOM_EDIT_HANDLER(Fx_FLT_MyEffect_Gain_edit, 2, 20);  /* params[5] */
ZOOM_EDIT_HANDLER(Fx_FLT_MyEffect_Tone_edit, 3, 24);  /* params[6] */
ZOOM_EDIT_HANDLER(Fx_FLT_MyEffect_Mix_edit,  4, 28);  /* params[7] */
```

Keep writable `.fardata` tiny. The linker rejects large writable images by
default because big static state has frozen real pedals during load. For large
stateful ports, use the proven `ctx[3]` descriptor arena and validate the
descriptor before touching memory. `StereoChorus` proves this can work, but
`ToTape9` currently crashes on load, so new full-kernel ports still need a
load-safety ladder: audio-NOP with the final UI shape, tiny pass-through DSP,
then helper-free DSP increments.
