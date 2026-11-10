"""Fake generate.py for UI testing without a GPU (WAN_MOCK=1).

Prints the same log lines as generate.py (so the server's progress parsing is exercised)
and writes a short slow-zoom video made from the input image. A prompt containing "FAIL"
simulates a crash after the first segment (10 s / 15 s videos only) (to test partial videos).
"""
import argparse
import os
import sys
import time
from pathlib import Path

import imageio
import numpy as np
from PIL import Image

p = argparse.ArgumentParser()
p.add_argument("image"); p.add_argument("prompt"); p.add_argument("--res"); p.add_argument("--sec", type=float, default=5)
p.add_argument("--steps", type=int, default=4); p.add_argument("--seed"); p.add_argument("--neg"); p.add_argument("--out")
p.add_argument("--lora", nargs=3, action="append")
a = p.parse_args()
t0 = time.time()


def log(m):
    print(f"[{time.time() - t0:7.1f}s] {m}", flush=True)


def clip(img, n=24):
    """A small slow zoom-in on the input image."""
    w, h = img.size
    frames = []
    for i in range(n):
        z = 1 + 0.15 * i / n
        cw, ch = int(w / z), int(h / z)
        f = img.crop(((w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch)).resize((w, h))
        frames.append(np.asarray(f))
    return frames


img = Image.open(a.image).convert("RGB")
img.thumbnail((480, 480))
img = img.resize((img.width // 16 * 16, img.height // 16 * 16))
out = Path(a.out)
part = out.with_name(out.stem + ".part.mp4")
log("text encoder…"); time.sleep(1)
log("expert high noise…"); time.sleep(1)
log("expert low noise…"); time.sleep(1)
n = max(1, int(-(-a.sec // 5)))
frames = []
for s in range(n):
    log(f"segment {s + 1}/{n}: {img.width}x{img.height}, 81 frames, {a.steps} steps, cfg 1.0, seed {a.seed or 1234}")
    for k in range(a.steps + 1):
        sys.stdout.write(f"\r{k * 100 // a.steps}%|###| {k}/{a.steps} [00:01<00:01, 1.00s/it]"); sys.stdout.flush(); time.sleep(1)
    print(); log(f"segment {s + 1} done, peak 1.0 GB")
    frames += clip(img)
    imageio.mimwrite(str(part), frames, fps=16, macro_block_size=16)
    if s == 0 and n > 1 and "FAIL" in a.prompt:
        raise RuntimeError("mock: simulated crash after segment 1")
os.replace(part, out)
log(f"DONE ({a.sec:.1f} s) -> {out}")
