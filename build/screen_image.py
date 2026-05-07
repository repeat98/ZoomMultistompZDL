"""128×64 monochrome canvas + Zoom RLE encoder.

Extracted from v1's `link_zdl.py` (build_screen_image) and generalized
so per-plugin image generators don't have to drag the linker along.

The Zoom on-screen image format:
* 128 wide × 64 tall, 1-bit-per-pixel monochrome
* Stored column-major in 8 row-blocks of 8 pixels each (i.e. each byte
  encodes 8 vertical pixels at a fixed (column, row_block) position)
* RLE-compressed: a doubled byte (`X X`) introduces a run-length byte
  whose value n means "repeat X n more times" (so total occurrences =
  n + 2)
* Output padded to a multiple of 4 bytes
"""

from __future__ import annotations
import math


class Canvas:
    """Tiny 128×64 1-bpp drawing surface."""

    W, H = 128, 64

    def __init__(self) -> None:
        self.pixels = [[0] * self.W for _ in range(self.H)]

    # ---- primitives -----------------------------------------------------
    def px(self, x: int, y: int, v: int = 1) -> None:
        if 0 <= x < self.W and 0 <= y < self.H:
            self.pixels[y][x] = v

    def hline(self, x0: int, x1: int, y: int, v: int = 1) -> None:
        if x0 > x1:
            x0, x1 = x1, x0
        for x in range(x0, x1 + 1):
            self.px(x, y, v)

    def vline(self, x: int, y0: int, y1: int, v: int = 1) -> None:
        if y0 > y1:
            y0, y1 = y1, y0
        for y in range(y0, y1 + 1):
            self.px(x, y, v)

    def rect(self, x0: int, y0: int, x1: int, y1: int, v: int = 1) -> None:
        self.hline(x0, x1, y0, v)
        self.hline(x0, x1, y1, v)
        self.vline(x0, y0, y1, v)
        self.vline(x1, y0, y1, v)

    def circle(self, cx: int, cy: int, r: int, v: int = 1) -> None:
        x, y, err = r, 0, 0
        while x >= y:
            for dx, dy in [(x, y), (-x, y), (x, -y), (-x, -y),
                           (y, x), (-y, x), (y, -x), (-y, -x)]:
                self.px(cx + dx, cy + dy, v)
            if err <= 0:
                y += 1
                err += 2 * y + 1
            if err > 0:
                x -= 1
                err -= 2 * x + 1

    def filled_circle(self, cx: int, cy: int, r: int, v: int = 1) -> None:
        for dy in range(-r, r + 1):
            w = int((r * r - dy * dy) ** 0.5)
            self.hline(cx - w, cx + w, cy + dy, v)

    # ---- text -----------------------------------------------------------
    _FONT = {
        'A': ["010", "101", "111", "101", "101"], 'B': ["110", "101", "110", "101", "110"],
        'C': ["011", "100", "100", "100", "011"], 'D': ["110", "101", "101", "101", "110"],
        'E': ["111", "100", "110", "100", "111"], 'F': ["111", "100", "110", "100", "100"],
        'G': ["011", "100", "101", "101", "011"], 'H': ["101", "101", "111", "101", "101"],
        'I': ["111", "010", "010", "010", "111"], 'J': ["001", "001", "001", "101", "010"],
        'K': ["101", "101", "110", "101", "101"], 'L': ["100", "100", "100", "100", "111"],
        'M': ["101", "111", "111", "101", "101"], 'N': ["101", "111", "111", "101", "101"],
        'O': ["010", "101", "101", "101", "010"], 'P': ["110", "101", "110", "100", "100"],
        'Q': ["010", "101", "101", "111", "011"], 'R': ["110", "101", "110", "101", "101"],
        'S': ["011", "100", "010", "001", "110"], 'T': ["111", "010", "010", "010", "010"],
        'U': ["101", "101", "101", "101", "011"], 'V': ["101", "101", "101", "010", "010"],
        'W': ["101", "101", "111", "111", "101"], 'X': ["101", "101", "010", "101", "101"],
        'Y': ["101", "010", "010", "010", "010"], 'Z': ["111", "001", "010", "100", "111"],
        '0': ["010", "101", "101", "101", "010"], '1': ["010", "110", "010", "010", "111"],
        '2': ["110", "001", "010", "100", "111"], '3': ["110", "001", "110", "001", "110"],
        '4': ["101", "101", "111", "001", "001"], '5': ["111", "100", "110", "001", "110"],
        '6': ["011", "100", "110", "101", "010"], '7': ["111", "001", "010", "100", "100"],
        '8': ["010", "101", "010", "101", "010"], '9': ["111", "101", "111", "001", "110"],
        ' ': ["000"] * 5, '-': ["000", "000", "111", "000", "000"],
        '.': ["000", "000", "000", "000", "010"], '!': ["010", "010", "010", "000", "010"],
    }

    def draw_char(self, ch: str, x0: int, y0: int, scale: int = 1) -> None:
        rows = self._FONT.get(ch.upper(), self._FONT[' '])
        for row_i, row in enumerate(rows):
            for col_i, bit in enumerate(row):
                if bit == '1':
                    for sy in range(scale):
                        for sx in range(scale):
                            self.px(x0 + col_i * scale + sx, y0 + row_i * scale + sy)

    def draw_text(self, text: str, x0: int, y0: int, scale: int = 1, spacing: int = 1) -> None:
        x = x0
        for ch in text:
            self.draw_char(ch, x, y0, scale)
            x += 3 * scale + spacing


# ---------------------------------------------------------------------------
# Zoom RLE encoder
# ---------------------------------------------------------------------------

def encode_zoom_rle(canvas: Canvas) -> bytes:
    """Encode a 128×64 canvas as Zoom's column-major 1-bpp RLE blob."""
    raw: list[int] = []
    for yx in range(8):                       # 8 row-blocks of 8 rows each
        for x in range(canvas.W):
            byte = 0
            for z in range(8):
                y = yx * 8 + z
                if canvas.pixels[y][x]:
                    byte |= (1 << z)
            raw.append(byte)

    compressed: list[int] = []
    i = 0
    while i < len(raw):
        if i + 1 < len(raw) and raw[i] == raw[i + 1]:
            j = i + 2
            while j < len(raw) and raw[j] == raw[i]:
                j += 1
            # Doubled marker followed by run-length-2 byte
            compressed.extend([raw[i], raw[i], j - i - 2])
            i = j
        else:
            compressed.append(raw[i])
            i += 1

    while len(compressed) % 4:
        compressed.append(0)
    return bytes(compressed)


def make_text_screen(name: str) -> bytes:
    """Default screen image: just the effect name centered, in big block letters."""
    c = Canvas()
    c.rect(0, 0, c.W - 1, c.H - 1)
    n = name.upper()[:8]
    scale = 3 if len(n) <= 4 else 2
    char_w = 3 * scale + 1
    text_w = char_w * len(n) - 1
    x0 = (c.W - text_w) // 2
    y0 = 12
    c.draw_text(n, x0, y0, scale=scale, spacing=1)
    return encode_zoom_rle(c)
