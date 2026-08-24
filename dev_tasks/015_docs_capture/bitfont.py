"""A 5x7 bitmap font, drawn with numpy.

The POR's annotation section argues against baking text into images: it is
unsearchable, cannot be corrected without re-rendering, and drags in
cross-machine font determinism. A tableau is the exception — a grid of cells
that does not say which cell is which has failed at its only job.

So the labels are baked, but with a font that is *data in this file* rather
than a system resource. Same pixels on every machine, no Pillow, no GL, no BLF.

Glyphs are 5 wide x 7 tall, one string per row.
"""
from __future__ import annotations

import numpy as np

GLYPHS = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01110", "10001", "10000", "10000", "10000", "10001", "01110"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "0": ("01110", "10011", "10101", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11111", "00010", "00100", "00010", "00001", "10001", "01110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    " ": ("00000",) * 7,
    "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    "/": ("00001", "00010", "00010", "00100", "01000", "01000", "10000"),
}

GLYPH_W, GLYPH_H = 5, 7
UNKNOWN = ("11111", "10001", "10001", "10001", "10001", "10001", "11111")


def text_mask(text, scale=1):
    """A boolean mask of the rendered text, origin TOP-left, 1px letterspace."""
    chars = [GLYPHS.get(c.upper(), UNKNOWN) for c in text]
    if not chars:
        return np.zeros((0, 0), dtype=bool)
    width = len(chars) * (GLYPH_W + 1) - 1
    mask = np.zeros((GLYPH_H, width), dtype=bool)
    for i, rows in enumerate(chars):
        x = i * (GLYPH_W + 1)
        for y, row in enumerate(rows):
            for dx, bit in enumerate(row):
                if bit == "1":
                    mask[y, x + dx] = True
    if scale > 1:
        mask = np.repeat(np.repeat(mask, scale, axis=0), scale, axis=1)
    return mask


def draw_text(frame, text, x, y, scale=3, color=(1.0, 1.0, 1.0),
              shadow=(0.0, 0.0, 0.0)):
    """Draw into an RGBA float array whose origin is BOTTOM-left (Blender's).

    `x`, `y` are the top-left of the text in *image* coordinates, counting
    from the top — which is how anyone reading the picture thinks about it.
    """
    mask = text_mask(text, scale)
    if mask.size == 0:
        return frame
    # text_mask is top-down; the frame is bottom-up, so the glyph rows have to
    # be flipped or the letters come out upside down.
    mask = mask[::-1]
    height = frame.shape[0]
    rows, cols = mask.shape
    top = height - y - rows  # flip into Blender's bottom-up rows

    def blit(off_x, off_y, rgb):
        y0, x0 = top + off_y, x + off_x
        if y0 < 0 or x0 < 0 or y0 + rows > frame.shape[0] \
                or x0 + cols > frame.shape[1]:
            return
        target = frame[y0:y0 + rows, x0:x0 + cols, :3]
        target[mask] = rgb

    # A one-pixel shadow keeps the label legible over both the pale surface
    # ink and the dark viewport background.
    if shadow is not None:
        blit(scale, -scale, shadow)
    blit(0, 0, color)
    return frame
