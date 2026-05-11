# Airwindows Port Layout

Each effect directory is meant to be buildable on its own and through
`python3 build_all.py`.

Required files:

- `manifest.json`: effect name, category, fxid, version, and 1-9 params.
- `build.py`: compiles the C file with TI `cl6x`, then calls
  `build/linker.py`.
- `<effect>.c`: exports `Fx_FLT_<Name>` in `.audio`.

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
