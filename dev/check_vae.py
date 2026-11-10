"""VAE decode benchmark. Usage: check_vae.py [float32|bfloat16] [notile]"""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root
import os, sys, time
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")
import torch
from diffusers import AutoencoderKLWan
import generate as g
dt = torch.float32 if len(sys.argv) < 2 else getattr(torch, sys.argv[1])
tiling = "notile" not in sys.argv
vae = AutoencoderKLWan.from_single_file(str(g.M/"vae"/"wan_2.1_vae.safetensors"), config=str(g.CFG), subfolder="vae", torch_dtype=dt).to("cuda")
if tiling: vae.enable_tiling()
lat = torch.randn(1, 16, 9, 78, 78, device="cuda", dtype=dt)  # 33 frames at 624x624
print("decode", dt, "tiling", tiling, flush=True); t = time.time()
with torch.no_grad(): out = vae.decode(lat).sample
torch.cuda.synchronize()
print("OK", tuple(out.shape), round(time.time()-t, 1), "s, peak", round(torch.cuda.max_memory_allocated()/1e9, 1), "GB", flush=True)
