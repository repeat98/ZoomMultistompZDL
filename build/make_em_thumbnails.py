#!/usr/bin/env python3
"""Write same-name PNG sidecars for Zoom Effect Manager from actual ZDL art."""
import argparse
from pathlib import Path
from PIL import Image
from decode_picture import decode_picture
from lcd_geometry import PIXEL_ASPECT

ROOT = Path(__file__).resolve().parents[1]

def render(zdl):
    pixels, _ = decode_picture(str(zdl))
    h, w = len(pixels), len(pixels[0])
    # ZEM's bundled icons are 128x96 RGBA masks: black opaque ink and
    # transparent white background. Opaque RGB images become solid tinted cards.
    cover = Image.new('RGBA', (w, h))
    cover.putdata([(0, 0, 0, 255) if bit else (255, 255, 255, 0)
                   for row in pixels for bit in row])
    height = min(96, round(128 * h / w * PIXEL_ASPECT))
    cover = cover.resize((128, height), Image.Resampling.NEAREST)
    icon = Image.new('RGBA', (128, 96), (255, 255, 255, 0))
    icon.paste(cover, (0, (96-height)//2))
    icon.save(zdl.with_suffix('.png'))
    return zdl.with_suffix('.png')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', nargs='?', type=Path, default=ROOT/'dist')
    args = p.parse_args()
    paths = sorted(args.folder.glob('*.ZDL'))
    if not paths: p.error('No ZDL files in the folder')
    for zdl in paths: render(zdl)
    print(f'Wrote {len(paths)} Effect Manager PNG sidecars in {args.folder}')

if __name__ == '__main__':
    main()
