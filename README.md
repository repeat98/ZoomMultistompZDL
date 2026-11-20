# MultiStomp effect releases

This collection contains the build recipe for 28 effects for the Zoom MS-70CDR running OS 2.10. Each effect has its own release tag, download and SHA-256 in manifest.json. Hardware untested. The release files passed the Ziddle loader and a half-second stereo render at the default settings. Pedal controls, live display, performance and saved patch recall still need a pedal test.

The effects and editor artwork come from [Roman Rusinov’s project](https://github.com/themanro/ZoomMultistompZDL/tree/aee98c53d7b568cbb55bb927aefbdc9b4e739f3e). The runtime comes from the [pinned own-runtime release](https://github.com/repeat98/ZoomMultistompZDL/tree/32f3d6877d892409c6defeeeec57040ad004d31f). Individual licences and credits for the effects, artwork, toolchain and runtime are in licenses/.

To reproduce the files, install the TI C6000 8.5.0.LTS compiler for the effect build scripts, clone both source repositories and supply the local comparison directory used by the runtime’s stock-code checker. With Python 3.12 or later, run the following command from this checkout.

```sh
python3 build/verify-rebuild.py /path/to/effects-checkout /path/to/runtime-checkout /path/to/local/comparison-directory
```

The script takes the source from the two pinned commits, applies the own-runtime linker and display identification change, and builds each effect in a temporary directory. It checks each output against its release SHA-256 and scans it with the runtime’s stock-code checker. The nine effects with a live display use an aggregate firmware checksum to identify a supported OS.
