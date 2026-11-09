# Tonic 0.01 — experimental

An independent Catalinbread Bitters-inspired design for MS-70CDR, built from the
public control description: https://catalinbread.com/products/catalinbread-bitters
This follows the documented topology, not a measured or exact sonic emulation.
Rewire remains unchanged. New identity: FXID 499, Delay category, patch ID
1080427280. Six controls, two edit pages; normal custom-effect listing in PE.

| Control | Behavior |
| --- | --- |
| Mode | Decim / Crush / FM / Ring; named positions |
| Amount | Selected effect amount; zero bypasses the stage |
| Drive | Compensated cubic distortion; zero bypasses the stage |
| Phase | Six-stage sine-swept phaser; zero bypass, up to 20 Hz |
| Order | Fwd = Drive → Phase → Mode; Rev reverses this chain |
| Mix | Exact stereo dry at zero; mono wet at 100 |

Decim reduces sample rate without reducing word length. Crush reduces word
length toward a two-level one-bit output and gates the crusher on silence.
FM uses an interpolated, modulated delay for pitch vibrato; with dry mixed in
it can make chorus-like sounds. Ring uses a sine carrier from about 20 Hz to
4 kHz. These ranges/topologies are our implementation choices, not measured
Catalinbread values. Mode and order changes fade through dry and reset history.

Start with Drive 0 / Phase 0 / Mix 50, then try each Mode with Amount 30–70.
For the one-bit extreme try Crush / Amount 100 at a comfortable listening level.
FM / Amount 20–35 / Mix 50 is the gentler starting point. Raise Drive and Phase
after learning each mode; reverse Order to hear how distortion placement changes
the result. With all three stage amounts zero the effect preserves stereo dry,
including at Mix 100.

## Build and checks

`python3 src/custom/tonic/build.py` builds `dist/Tonic.ZDL`. `build_all.py tonic`
also builds it explicitly; it is not included in default release-pack builds
until hardware validation. Use the project's NumPy/Pillow-capable Python.

`python3 src/custom/tonic/validate_host.py --samples` compiles the actual DSP C
for host testing and writes reports and four guitar samples under
`build/tonic-validation/`. The examples are host renders, not pedal recordings.

Verified: guarded state, exact stereo dry and bypass, zero-stage unity, all mode
ranges, full wet endpoint, different routing orders, one-bit output and gate
closure, independent instances, bounded mode/order transitions. The TI build has
no writable static state, unexpected helper functions, jump-table sections or
audio relocations. Label callbacks and six-control initialization were audited.
These checks do not replace hardware listening or measure TI execution time.

Reinstall/restart Effect Manager to see Tonic under Delay with its PNG sidecar.
Reload PE after installing for its new controls and graphic. No pedal writes
have been performed automatically. NAMLite is a separate ongoing experiment.
