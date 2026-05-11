# Airwindows Port Layout

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

Keep writable `.fardata` tiny. The linker rejects large writable images
by default because big static state has frozen real pedals during load.
Until the state ABI is solved, prefer stateless or very small-state beta
ports.
