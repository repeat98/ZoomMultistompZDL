# CD BHS Singularity Fuzz capture check

Checked 2026-09-23. The user-supplied capture is compatible with the current
A2 Lite converter. **Local dist currently contains the 0.12 Marlboro Smokey Amp candidate,
not this fuzz capture. Hardware validation is pending.** The 0.06 fuzz build is preserved under
`build/probes/namlite/compact-0.06/`.
Version 0.05 loaded and passed audio without freezing, but the user reported
excessive noise and a bitcrushed character. Version 0.06 adds finer low-input
attenuation; the user reports improvement but a persistent bitcrushed texture.
The user confirmed the 0.07 diagnostic sounded clean; the 0.08 megaphone still
sounded bitcrushed. The 0.09 history test produced its expected delay but remained bitcrushed.
The 0.10 candidate changes execution and memory layout; the root cause remains
unconfirmed.
The working 0.03 fallback is preserved separately;
see [NAMLite build notes](../src/hardware_probes/namlite/README.md).

Source: `CD BHS Singularity Fuzz.nam`, supplied from Downloads. Metadata names
Collision Devices Black Hole Symmetry, modeled by `jgma`, trainer TONE3000.
The source capture and generated weights have not been added to tracked files.

SHA-256: `b7467149fb2e9839fd9a8142ed98962373f06b6d18605f9a2bf2697dea074713`.

The 48 kHz SlimmableContainer contains:

| Submodel | Channels | Weights | Selected |
| --- | --- | --- | --- |
| Lite (max_value 0.5) | 3 | 1,871 | Yes |
| Larger (max_value 1) | 8 | 12,146 | No |

The selected network has the same 23-layer geometry as the earlier example.
Generated state is 112,612 bytes; weighted products per sample: 1,732. TI C674x
O2 compilation succeeded with a 42,400-byte `.text` section and no named external
helpers. This is a kernel object, not a complete or hardware-tested ZDL.

Host comparison against official NAM Core's A2 fast engine gave exact float32
agreement for 16,384 samples each of silence, impulse, seeded noise and a 440 Hz
sine. Eight-sample vs 257-sample block processing and resets also matched exactly.
Reference prewarming was disabled for both implementations. These results do
not establish real-time TI performance or pedal compatibility.

Local generated files and validation report:
`build/probes/namlite/captures/singularity/`.

Reproduce from repository root with the existing reference NAM Core checkout:

```sh
python3 tools/nam_prototype/generate.py "$HOME/Downloads/CD BHS Singularity Fuzz.nam" build/probes/namlite/captures/singularity
python3 tools/nam_prototype/validate.py build/probes/namlite/captures/singularity /tmp/ms-nam-core
```

See [prototype notes](NAM-A2-LITE-PROTOTYPE.md) for the pinned NAM Core reference.
The earlier large-ZDL loading/initialization failure led to the compact build
below. This capture also needs the same 48-to-44.1 kHz
rate handling as the earlier model for faithful reproduction.

The compact generator subsequently passed the same exact host comparison and
produced a complete 15,906-byte ZDL with 2,944 audio-code bytes. This reduces
the earlier code footprint substantially without changing the network math.
Hardware testing subsequently confirmed 0.05 loads without freezing. This does
not establish audio fidelity or real-time timing. Quiet-input tests show roughly
56.5 dB small-signal gain in the official capture itself, reproduced exactly by
our host kernel. See the build notes for the 0.06 attenuation test and limitations.
