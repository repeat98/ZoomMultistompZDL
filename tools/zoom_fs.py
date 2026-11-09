#!/usr/bin/env python3
"""Read and build the effect file system of a ZDL MultiStomp pedal (MS-70CDR).

Layout as written by Zoom Effect Manager 2 (docs/EFFECT-INSTALL-PROTOCOL.md):
a 16-byte header, a directory of 32-byte entries at 0x3000, then 4,096-byte
clusters from 0xA000, each with a 6-byte header (previous, next, bytes used)
and up to 4,090 bytes of data. Effect Manager writes the files one after
another from cluster 1, in directory order.

    python3 tools/zoom_fs.py list  IMAGE
    python3 tools/zoom_fs.py extract IMAGE OUTDIR      (files + order.txt)
    python3 tools/zoom_fs.py build OUTDIR IMAGE        (from order.txt)
    python3 tools/zoom_fs.py check IMAGE               (extract, rebuild, compare)
    python3 tools/zoom_fs.py stock UPDATER OUTDIR [--strip]
        Zoom's stock effects from your own copy of the pedal's updater (.zip,
        .app/.exe folder or its FS.bin). --strip removes their debug sections
        with TI's strip6x, as Effect Manager installs them.

Offline only: nothing here talks to a pedal. Images and extracted files
contain Zoom's effects; keep them on your own computer.
"""
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SIZE = 0x2C7000              # the file system region, flash 0x0F0000..0x3B7000
HEADER = bytes.fromhex("55aa00010400c800c702")   # as Effect Manager writes it; meaning not decoded
DIR_AT, ENTRY = 0x3000, 32
DATA_AT, CLUSTER, CL_HDR = 0xA000, 0x1000, 6
PAYLOAD = CLUSTER - CL_HDR
FIRST_ENTRY_TAG = bytes.fromhex("01a50200ffffffff")   # bytes 0-7 of the first entry; meaning unknown
NONE = 0xFFFF


def read(image: bytes) -> list[tuple[str, bytes]]:
    files, at = [], DIR_AT
    while at + ENTRY <= DATA_AT and image[at + 16] != 0xFF:
        entry = image[at:at + ENTRY]
        cluster, size = struct.unpack_from("<H", entry, 8)[0], struct.unpack_from("<I", entry, 12)[0]
        name = entry[16:28].split(b"\xff")[0].rstrip(b"\x00").decode("ascii")
        data, seen = bytearray(), set()
        while len(data) < size:
            if cluster == NONE or cluster in seen:
                raise ValueError(f"{name}: broken cluster chain")
            seen.add(cluster)
            base = DATA_AT + cluster * CLUSTER
            _, nxt, used = struct.unpack_from("<HHH", image, base)
            data += image[base + CL_HDR:base + CL_HDR + used]
            cluster = nxt
        if len(data) != size:
            raise ValueError(f"{name}: chain holds {len(data)} bytes, directory says {size}")
        files.append((name, bytes(data)))
        at += ENTRY
    return files


def _chain(image: bytes, cluster: int, size: int) -> bytes | None:
    data, seen = bytearray(), set()
    while len(data) < size:
        base = DATA_AT + cluster * CLUSTER
        if cluster == NONE or cluster in seen or base + CL_HDR > len(image):
            return None
        seen.add(cluster)
        _, nxt, used = struct.unpack_from("<HHH", image, base)
        data += image[base + CL_HDR:base + CL_HDR + used]
        cluster = nxt
    return bytes(data) if len(data) == size else None


def read_updater(image: bytes) -> dict[str, bytes]:
    """Files in a shipped FS.bin. Unlike an Effect Manager image, it holds
    several directory copies; an entry whose byte 11 is 00 is a superseded one.
    The last valid entry for a name wins."""
    files = {}
    for at in range(DIR_AT, DATA_AT, ENTRY):
        entry = image[at:at + ENTRY]
        if entry[16] == 0xFF or entry[11] != 0xFF:
            continue
        name = entry[16:28].split(b"\xff")[0].rstrip(b"\x00").decode("latin-1")
        data = _chain(image, struct.unpack_from("<H", entry, 8)[0], struct.unpack_from("<I", entry, 12)[0])
        if data is not None:
            files[name] = data
    return files


def updater_fs(path: Path) -> bytes:
    """FS.bin from an updater: the .zip as downloaded, an unpacked folder, or FS.bin itself."""
    if path.is_dir():
        found = [p for p in path.rglob("FS.bin")]
        if len(found) != 1:
            raise ValueError(f"expected one FS.bin under {path}, found {len(found)}")
        return found[0].read_bytes()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith("/FS.bin") or n == "FS.bin"]
            if len(names) != 1:
                raise ValueError(f"expected one FS.bin in {path}, found {len(names)}")
            return archive.read(names[0])
    return path.read_bytes()


STRIP6X = os.environ.get("STRIP6X", "/Applications/ti/ti-cgt-c6000_8.5.0.LTS/bin/strip6x")
ZDL_HEADER = 0x4C            # bytes before the ELF; the size field at 0x10 is the ELF's length


def strip(zdl: bytes) -> bytes:
    """Remove the ELF's debug sections with TI's strip6x and fix the ZDL size field.
    On the 2.10 captures this matches Effect Manager's copy of every effect checked."""
    if zdl[ZDL_HEADER:ZDL_HEADER + 4] != b"\x7fELF":
        raise ValueError("not a ZDL")
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder, "in.elf"), Path(folder, "out.elf")
        source.write_bytes(zdl[ZDL_HEADER:])
        subprocess.run([STRIP6X, f"-o={target}", str(source)], check=True, capture_output=True)
        elf = target.read_bytes()
    header = bytearray(zdl[:ZDL_HEADER])
    struct.pack_into("<I", header, 0x10, len(elf))
    return bytes(header) + elf


def build(files: list[tuple[str, bytes]]) -> bytes:
    image = bytearray(b"\xff" * SIZE)
    image[0:len(HEADER)] = HEADER
    if (DATA_AT - DIR_AT) // ENTRY < len(files):
        raise ValueError("too many files for the directory")
    cluster = 1
    for index, (name, data) in enumerate(files):
        raw = name.encode("ascii")
        if len(raw) > 12 or "." not in name:
            raise ValueError(f"{name}: expected an 8.3 name")
        count = max(1, -(-len(data) // PAYLOAD))
        if DATA_AT + (cluster + count) * CLUSTER > SIZE:
            raise ValueError(f"{name}: file system full")
        entry = bytearray(b"\xff" * ENTRY)
        if index == 0:
            entry[0:8] = FIRST_ENTRY_TAG
        struct.pack_into("<HB", entry, 8, cluster, 0x01)
        struct.pack_into("<I", entry, 12, len(data))
        entry[16:28] = raw.ljust(12, b"\x00")
        image[DIR_AT + index * ENTRY:DIR_AT + (index + 1) * ENTRY] = entry
        for k in range(count):
            part = data[k * PAYLOAD:(k + 1) * PAYLOAD]
            base = DATA_AT + (cluster + k) * CLUSTER
            prev = NONE if k == 0 else cluster + k - 1
            nxt = NONE if k == count - 1 else cluster + k + 1
            struct.pack_into("<HHH", image, base, prev, nxt, len(part))
            image[base + CL_HDR:base + CL_HDR + len(part)] = part
        cluster += count
    return bytes(image)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    command = argv[0]
    if command == "list":
        for name, data in read(Path(argv[1]).read_bytes()):
            print(f"{name:12} {len(data):7}")
    elif command == "extract":
        out = Path(argv[2]); out.mkdir(parents=True, exist_ok=True)
        files = read(Path(argv[1]).read_bytes())
        for name, data in files:
            (out / name).write_bytes(data)
        (out / "order.txt").write_text("".join(name + "\n" for name, _ in files))
        print(f"{len(files)} files -> {out}")
    elif command == "build":
        folder = Path(argv[1])
        names = [line.strip() for line in (folder / "order.txt").read_text().splitlines() if line.strip()]
        Path(argv[2]).write_bytes(build([(name, (folder / name).read_bytes()) for name in names]))
        print(f"{len(names)} files -> {argv[2]}")
    elif command == "stock":
        out = Path(argv[2]); out.mkdir(parents=True, exist_ok=True)
        files = read_updater(updater_fs(Path(argv[1])))
        for name, data in sorted(files.items()):
            (out / name).write_bytes(strip(data) if "--strip" in argv and name.upper().endswith(".ZDL") else data)
        print(f"{len(files)} files -> {out}")
    elif command == "check":
        image = Path(argv[1]).read_bytes()
        if len(image) != SIZE:
            print(f"expected {SIZE} bytes, got {len(image)}")
            return 1
        rebuilt = build(read(image))
        if rebuilt == image:
            print("identical: the rebuilt image matches byte for byte")
            return 0
        diffs = [i for i in range(SIZE) if rebuilt[i] != image[i]]
        print(f"{len(diffs)} bytes differ, first at 0x{diffs[0]:x}")
        return 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
