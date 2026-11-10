"""Wan 2.2 A14B I2V – image + prompt -> mp4, without ComfyUI.

Usage (via generate.bat or directly):
  python generate.py image.jpg "prompt" [--res 480|720] [--sec 5] [--steps 4] [--seed 42]
                     [--lora high.safetensors low.safetensors 1.0]   (repeatable)

Videos longer than --seg (default 5 s) are built from chained segments: each segment
starts from the last frame of the previous one (models stay loaded).

Memory: the weights are loaded from disk straight into VRAM (device="cuda") and nothing large stays in RAM.
The text encoder is freed right after the prompt is encoded.
"""
import argparse
import gc
import os
import threading
import time
from pathlib import Path

# AMD gfx1151: without this PyTorch falls back to "math" attention -> tens of GB extra and OOM
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")

import numpy as np
import torch

torch.backends.cuda.enable_flash_sdp(True)
torch.backends.cuda.enable_mem_efficient_sdp(True)
from PIL import Image
from safetensors.torch import load_file

from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanImageToVideoPipeline, WanTransformer3DModel
from diffusers.utils import export_to_video
from transformers import AutoTokenizer, UMT5Config, UMT5EncoderModel

ROOT = Path(__file__).resolve().parent
M = ROOT / "models"
CFG = M / "diffusers-config"
FPS = 16
DEV = "cuda"
DT = torch.bfloat16
NEG = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，"
       "JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，"
       "手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")  # official Wan negative prompt
LIGHTX = ("wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
          "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors")


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


def vram():
    return f"VRAM {torch.cuda.memory_allocated() / 1e9:.1f} GB"


def free():
    gc.collect()
    torch.cuda.empty_cache()


def load_text_encoder():
    cfg = UMT5Config.from_pretrained(CFG / "text_encoder")
    sd = load_file(M / "text_encoders" / "umt5_xxl_fp16.safetensors", device=DEV)
    sd.pop("spiece_model", None)
    sd.setdefault("encoder.embed_tokens.weight", sd["shared.weight"])
    with torch.device("meta"):
        te = UMT5EncoderModel(cfg)
    missing, unexpected = te.load_state_dict(sd, strict=False, assign=True)
    if missing or unexpected:
        log(f"text encoder: missing={missing} unexpected={unexpected}")
    return te.to(DT).eval()


def load_transformer(fname, sub, loras):
    """Weights straight into VRAM; LoRAs are fused and the adapters dropped (as fast as running without LoRA)."""
    t = WanTransformer3DModel.from_single_file(
        str(M / "diffusion_models" / fname), config=str(CFG), subfolder=sub, torch_dtype=DT, device=DEV)
    names = []
    for i, (path, w) in enumerate(loras):
        log(f"  LoRA {Path(path).name} (strength {w})")
        sd = WanImageToVideoPipeline.lora_state_dict(str(path))
        sd = sd[0] if isinstance(sd, tuple) else sd
        sd = WanImageToVideoPipeline._maybe_expand_t2v_lora_for_i2v(t, sd)
        t.load_lora_adapter(sd, adapter_name=f"l{i}")
        names.append(f"l{i}")
    if names:
        t.set_adapters(names, [w for _, w in loras])
        t.fuse_lora(adapter_names=names)
        t.unload_lora()
    free()
    return t.eval()


def watch_parent():
    """Exit when the Videogen Studio server dies – otherwise this process would keep holding ~60 GB of VRAM."""
    pid = int(os.environ.get("WAN_PARENT_PID") or 0)
    if not pid:
        return
    try:
        import psutil
        ct = psutil.Process(pid).create_time()
    except Exception:
        return

    def loop():
        while True:
            time.sleep(5)
            try:
                alive = psutil.Process(pid).create_time() == ct
            except Exception:
                alive = False
            if not alive:
                print("Studio server exited – stopping generation.", flush=True)
                os._exit(3)
    threading.Thread(target=loop, daemon=True).start()


def fit(img, max_area, mod=16):
    if img.width % mod == 0 and img.height % mod == 0 and img.width * img.height <= max_area * 1.02:
        return img   # already prepared at output size by the server
    ar = img.height / img.width
    h = round((max_area * ar) ** 0.5) // mod * mod
    w = round((max_area / ar) ** 0.5) // mod * mod
    return img.resize((w, h), Image.LANCZOS)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("image")
    p.add_argument("prompt")
    p.add_argument("--neg", default=NEG)
    p.add_argument("--res", type=int, default=480, choices=[480, 720])
    p.add_argument("--sec", type=float, default=5, help="total video length in seconds")
    p.add_argument("--seg", type=float, default=5, help="length of one segment (longer = more VRAM and much slower)")
    p.add_argument("--steps", type=int, default=4)
    p.add_argument("--cfg", type=float, default=None, help="default 1.0 with the 4-step LoRA, otherwise 3.5")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--lora", nargs=3, action="append", metavar=("HIGH", "LOW", "STRENGTH"))
    p.add_argument("--out", default=None)
    args = p.parse_args()
    watch_parent()

    fast = args.steps <= 8
    cfg = args.cfg if args.cfg is not None else (1.0 if fast else 3.5)
    seed = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "little")
    seg_frames = int(args.seg * FPS) // 4 * 4 + 1  # Wan wants 4k+1 frames
    n_seg = max(1, int(np.ceil(args.sec / args.seg - 1e-6)))
    img = fit(Image.open(args.image).convert("RGB"), 480 * 832 if args.res == 480 else 720 * 1280)
    out = Path(args.out) if args.out else ROOT / "output" / f"wan_{time.strftime('%Y%m%d_%H%M%S')}_{seed}.mp4"
    out.parent.mkdir(exist_ok=True)
    part = out.with_name(out.stem + ".part.mp4")   # work-in-progress file; final name only after the last segment

    # 1) prompt -> embeddings, then free the text encoder
    log("text encoder…")
    tok = AutoTokenizer.from_pretrained(CFG / "tokenizer")
    vae = AutoencoderKLWan.from_single_file(
        str(M / "vae" / "wan_2.1_vae.safetensors"), config=str(CFG), subfolder="vae",
        torch_dtype=torch.float32, device=DEV)
    vae.enable_tiling()
    sched = UniPCMultistepScheduler.from_pretrained(CFG / "scheduler")
    sched.register_to_config(flow_shift=3.0 if args.res == 480 else 5.0)
    pipe = WanImageToVideoPipeline(tokenizer=tok, text_encoder=load_text_encoder(), vae=vae, scheduler=sched,
                                   boundary_ratio=0.9)
    with torch.no_grad():
        pe, ne = pipe.encode_prompt(args.prompt, args.neg, do_classifier_free_guidance=cfg > 1.0, device=DEV)
    pipe.register_modules(text_encoder=None)
    free()
    log(f"prompt encoded, {vram()}")

    # 2) both experts straight into VRAM (2× 28.6 GB)
    extra = [(Path(h), Path(l), float(w)) for h, l, w in args.lora or []]
    hi = [(M / "loras" / LIGHTX[0], 1.0)] if fast else []
    lo = [(M / "loras" / LIGHTX[1], 1.0)] if fast else []
    hi += [(h, w) for h, _, w in extra]
    lo += [(l, w) for _, l, w in extra]
    log("expert high noise…")
    t1 = load_transformer("wan2.2_i2v_high_noise_14B_fp16.safetensors", "transformer", hi)
    log(f"expert low noise… ({vram()})")
    t2 = load_transformer("wan2.2_i2v_low_noise_14B_fp16.safetensors", "transformer_2", lo)
    pipe.register_modules(transformer=t1, transformer_2=t2)
    log(f"models loaded, {vram()}")

    # 3) segments
    all_frames = []
    start = img
    for s in range(n_seg):
        log(f"segment {s + 1}/{n_seg}: {img.width}x{img.height}, {seg_frames} frames, {args.steps} steps, "
            f"cfg {cfg}, seed {seed + s}")
        torch.cuda.reset_peak_memory_stats()
        with torch.no_grad():
            frames = pipe(image=start, prompt_embeds=pe, negative_prompt_embeds=ne,
                          height=img.height, width=img.width, num_frames=seg_frames,
                          num_inference_steps=args.steps, guidance_scale=cfg, guidance_scale_2=cfg,
                          output_type="np",
                          generator=torch.Generator("cpu").manual_seed(seed + s)).frames[0]
        log(f"segment {s + 1} done, peak {torch.cuda.max_memory_allocated() / 1e9:.1f} GB")
        all_frames.extend(frames if s == 0 else frames[1:])  # frame 0 = last frame of the previous segment
        start = Image.fromarray((np.clip(frames[-1], 0, 1) * 255).round().astype(np.uint8))
        free()
        # save after every segment so a crash does not lose finished segments
        export_to_video(all_frames, str(part), fps=FPS)

    os.replace(part, out)
    log(f"DONE ({len(all_frames) / FPS:.1f} s) -> {out}")


if __name__ == "__main__":
    main()
