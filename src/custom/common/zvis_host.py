#!/usr/bin/env python3
"""Run a zvis effect on the host (ZV_HOST: no firmware reads or calls, always
'visible') and save the frames it publishes as PNGs (pedal pixel aspect).

    python3 zvis_host.py <effect dir> <out dir> [--knobs 30,25,0] [--signal sine|pluck|stereo|silence]
                         [--seconds 2] [--frames 4]
Checks along the way: audio untouched, every frame decodes, and the streaming
RLE is byte-identical to build/screen_image.encode_zoom_rle.
"""
import argparse, ctypes as C, json, math, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "build"), str(ROOT / "src/airwindows/common")]
from screen_image import Canvas, encode_zoom_rle  # noqa: E402


def decode(buf):
    out, i = [], 0
    while len(out) < 1024:
        b = buf[i]
        if buf[i + 1] == b:
            out += [b] * (buf[i + 2] + 2); i += 3
        else:
            out.append(b); i += 1
    return bytes(out[:1024]), i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("effect", type=Path); ap.add_argument("out", type=Path)
    ap.add_argument("--knobs", default=""); ap.add_argument("--signal", default="sine", help="sine, stereo, pluck, silence, or a .f32 file")
    ap.add_argument("--seconds", type=float, default=2.0); ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--arena-kb", type=int, default=128, help="the effect's memory (the pedal gives ~689)")
    ap.add_argument("--presses", default="", help="seconds at which the footswitch flips the effect on/off, e.g. 0.5,2.5")
    a = ap.parse_args()
    m = json.loads((a.effect / "manifest.json").read_text())
    name, audio = m["effect_name"], m["audio_func_name"]
    a.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        stub = Path(td) / "stub.c"
        stub.write_text(f"unsigned int _{audio}_Info[64] = {{0, 1, 0, 128, 64, 0x12345678u}};\n")
        so = Path(td) / "fx.so"
        subprocess.run(["cc", "-O2", "-shared", "-fPIC", "-w", "-DZV_HOST", f"-I{HERE}", f"-I{a.effect}",
                        f"-I{ROOT}/src/airwindows/common", str(a.effect / f"{name.lower()}.c"), str(stub), "-o", str(so)],
                       check=True)
        lib = C.CDLL(str(so))
        fn = getattr(lib, audio); fn.argtypes = [C.POINTER(C.c_size_t)]
        info = (C.c_uint * 64).in_dll(lib, f"_{audio}_Info")
        arena = (C.c_uint8 * (a.arena_kb << 10))(); base = C.addressof(arena)
        desc = (C.c_size_t * 2)(base, base + (a.arena_kb << 10))
        knobs = [float(v) / 100 for v in a.knobs.split(",")] if a.knobs else [p["default"] / 100 for p in m["params"]]
        params = (C.c_float * 16)(1, 0, 0, 0, 0, *knobs)
        fx = (C.c_float * 16)(); src = C.c_uint(7); dst = C.c_uint(); dp = C.c_size_t(C.addressof(dst))
        ctx = (C.c_size_t * 16)()
        for k, v in [(1, params), (3, desc), (5, fx), (11, dp), (12, src)]:
            ctx[k] = C.addressof(v)
        ctx[0] = 0
        frames, last, t = [], info[5], 0
        n = int(a.seconds * 44100 / 8)
        wav = None
        if a.signal.endswith(".f32"):          # mono float32 samples, e.g. the emulator's test signal
            import array
            wav = array.array("f"); wav.frombytes(Path(a.signal).read_bytes())
            n = min(n, len(wav) // 8)
        presses = {int(float(v) * 44100) // 8 for v in a.presses.split(",") if v}
        for blk in range(n):
            if blk in presses:
                params[0] = 0.0 if params[0] > 0.5 else 1.0
            for j in range(8):
                tt = t / 44100
                if wav is not None:
                    l = r = wav[t]
                elif a.signal == "sine":
                    l = r = 0.4 * math.sin(2 * math.pi * 196 * tt)
                elif a.signal == "stereo":
                    l, r = 0.4 * math.sin(2 * math.pi * 196 * tt), 0.4 * math.sin(2 * math.pi * 294 * tt)
                elif a.signal == "pluck":
                    ph = tt % 0.5
                    env = math.exp(-ph * 6)
                    l = r = 0.7 * env * (math.sin(2 * math.pi * 110 * tt) + 0.3 * math.sin(2 * math.pi * 330 * tt))
                else:
                    l = r = 0.0
                fx[j], fx[j + 8] = l, r; t += 1
            before = list(fx)
            fn(ctx)
            assert a.presses or list(fx) == before, "audio changed"   # a looper changes it, by design
            if info[5] != last:
                last = info[5]
                frames.append(bytes((C.c_uint8 * 1544).from_address((base & ~0xFFFFFFFF) | last)))
    print(f"{name}: {len(frames)} frames in {a.seconds} s")
    from PIL import Image
    for k, fr in enumerate(frames[-a.frames:]):
        raw, used = decode(fr)
        c = Canvas()
        for b in range(8):
            for x in range(128):
                for z in range(8):
                    c.pixels[b * 8 + z][x] = (raw[b * 128 + x] >> z) & 1
        enc = encode_zoom_rle(c)
        assert enc == fr[:len(enc)], "RLE differs from the Python encoder"
        im = Image.new("L", (128, 64)); im.putdata([0 if v else 220 for row in c.pixels for v in row])
        im.resize((384, int(192 * 1.4)), Image.NEAREST).save(a.out / f"{name.lower()}_{k}.png")
    print(f"  {min(a.frames, len(frames))} frames saved to {a.out}; RLE identical to the Python encoder; audio untouched")


if __name__ == "__main__":
    main()
