# Hardware Probes

This directory contains diagnostic ZDLs used to reverse-engineer the Zoom
runtime ABI. They are not Airwindows ports and are not part of the normal
release set in `dist/`.

Build one probe by name:

```bash
python3 -B build_all.py ctxmap
python3 -B build_all.py descsize
```

Build release effects plus every probe:

```bash
python3 -B build_all.py --all
```

Each probe keeps its own `manifest.json`, `build.py`, and DSP source. Probe
build scripts reuse the shared linker and helper code from `build/` and
`src/airwindows/common/`.
