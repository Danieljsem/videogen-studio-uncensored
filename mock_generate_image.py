"""Fake generate_image.py for UI testing without a GPU (WAN_MOCK=1).

Prints the same log lines as generate_image.py and writes simple gradient images.
A prompt containing "FAIL" simulates a crash after the first image.
"""
import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from catalog import size_for

p = argparse.ArgumentParser()
p.add_argument("prompt"); p.add_argument("--neg"); p.add_argument("--aspect", default="1:1"); p.add_argument("--mp", type=float, default=1.0)
p.add_argument("--count", type=int, default=1); p.add_argument("--steps", type=int, default=30); p.add_argument("--cfg", type=float)
p.add_argument("--seed", type=int); p.add_argument("--model", default="chroma"); p.add_argument("--offload"); p.add_argument("--out")
a = p.parse_args()
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:7.1f}s] {m}", flush=True)


seed = a.seed if a.seed is not None else 1234
w, h = size_for(a.aspect, a.mp)
out = Path(a.out)
log("text encoder…"); time.sleep(1)
log("prompt encoded")
log("image model…"); time.sleep(1)
log("models loaded")
steps = min(a.steps, 6)
for i in range(a.count):
    s = seed + i
    log(f"image {i + 1}/{a.count}: {w}x{h}, {a.steps} steps, cfg {a.cfg or 3.0}, seed {s}")
    for k in range(steps + 1):
        sys.stdout.write(f"\r{k * 100 // steps}%|###| {k}/{steps} [00:01<00:01, 1.00s/it]"); sys.stdout.flush(); time.sleep(0.5)
    print()
    rgb = np.frombuffer(hashlib.sha256(f"{a.prompt}{s}".encode()).digest()[:6], np.uint8).reshape(2, 3).astype(float)
    t = np.linspace(0, 1, h)[:, None, None]
    arr = (rgb[0] * (1 - t) + rgb[1] * t).repeat(w, axis=1).astype(np.uint8)
    img = Image.fromarray(arr)
    ImageDraw.Draw(img).text((24, 24), f"MOCK {i + 1}/{a.count}\n{a.prompt[:60]}", fill=(255, 255, 255))
    dst = out if i == 0 else out.with_name(f"{out.stem}_{i + 1}.png")
    tmp = dst.with_name(dst.stem + ".part.png")
    img.save(tmp); os.replace(tmp, dst)
    log(f"SAVED {dst.name} seed {s}")
    if i == 0 and a.count > 1 and "FAIL" in a.prompt:
        raise RuntimeError("mock: simulated crash after image 1")
log(f"DONE ({a.count} images)")
