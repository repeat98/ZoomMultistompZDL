# NAMTest: stage 1

Build from repository root:

```sh
python3 src/hardware_probes/namtest/build.py
```

Output: `build/probes/namtest/NAMTest.ZDL`, version 0.01, Filter category,
GID 2 / FXID 497. Kept outside the release `dist` directory.

The audio function preserves the required ctx[11]/ctx[12] shuttle and leaves
all audio buffers untouched, following the current effects' in-place ABI.
There is no neural model, persistent state, allocation or rate conversion.
Input, Output and Mix are saved UI placeholders with no audio behavior in this
stage. This keeps the intended three-parameter layout for later neural tests.

Install using the usual custom-effect workflow. Test alone in a patch: audio
should pass unchanged, on/off should be transparent, all knobs should move and
retain their values after changing patches and after a power cycle.

Local validation: TI C674x compilation; parsed descriptor names/ranges/defaults;
no GID/FXID collision among source manifests; corrected init byte comparison;
init handler branches checked at load bases 0, 0x10000000 and 0x11820000;
final audio disassembly contains only the shuttle and return. Hardware results
are pending. This build does not test NAM performance.
