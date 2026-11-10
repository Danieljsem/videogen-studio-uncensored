"""Builds the Videogen Studio icon from plain geometric shapes (no font, no AI image) – MIT like the rest.

Outputs: studio/icon.png (512), studio/icon.ico (16–256) and web/favicon.png (64).
Run from the studio folder: python icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
S, K = 1024, 4                                  # design grid 1024×1024, drawn 4× larger for smooth edges
BG = (18, 12, 8)                                # near-black square, no rounded corners, no frame
TOP, BOTTOM = (255, 196, 40), (255, 150, 30)    # letter gradient: yellow-orange -> orange


def letters(d, fill, hole):
    p = lambda pts: [(x * K, y * K) for x, y in pts]
    # V – two strokes meeting at the bottom
    d.polygon(p([(130, 290), (240, 290), (345, 600), (450, 290), (560, 290), (400, 735), (290, 735)]), fill=fill)
    # g – square bowl, right stem going down, short square hook
    t, x0, y0, x1, y1 = 78, 615, 420, 895, 700
    d.rectangle(p([(x0, y0), (x1, y1)]), fill=fill)
    d.rectangle(p([(x0 + t, y0 + t), (x1 - t, y1 - t)]), fill=hole)
    d.rectangle(p([(x1 - t, y0), (x1, 880)]), fill=fill)
    d.rectangle(p([(x0 + 40, 880 - t), (x1, 880)]), fill=fill)


def build():
    size = (S * K, S * K)
    mask = Image.new("L", size, 0)
    letters(ImageDraw.Draw(mask), 255, 0)
    grad = Image.new("RGB", size)
    g = ImageDraw.Draw(grad)
    for y in range(size[1]):
        t = y / size[1]
        g.line([(0, y), (size[0], y)], fill=tuple(round(TOP[i] * (1 - t) + BOTTOM[i] * t) for i in range(3)))
    im = Image.new("RGB", size, BG)
    im.paste(grad, (0, 0), mask)
    return im.resize((S, S), Image.LANCZOS)


if __name__ == "__main__":
    im = build()
    im.resize((512, 512), Image.LANCZOS).save(HERE / "icon.png", optimize=True)
    im.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.resize((64, 64), Image.LANCZOS).save(HERE.parent / "web" / "favicon.png", optimize=True)
    print("icon.png, icon.ico, web/favicon.png written")
