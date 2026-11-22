"""Text -> image with Chroma1-HD (uncensored, Apache 2.0) or your own SDXL checkpoint.

Usage:
  python generate_image.py "prompt" [--aspect 1:1] [--count 1] [--steps 30] [--cfg 3.0] [--seed 42]
                           [--model chroma | <file in models/checkpoints>] [--out output/img_x.png]

Download the model first: python download_models.py image   (or the Download button in the app).

Memory: like generate.py, the prompt is encoded first and the text encoder is freed before the image model
is loaded, so the peak is the image model alone (~18 GB for Chroma in bf16). GPUs with less memory than that
switch to CPU offload automatically (slower, needs system RAM instead).
"""
import argparse
import gc
import os
import threading
import time
from pathlib import Path

from catalog import CHECKPOINTS, CHROMA_DIR, IMAGE_ASPECTS, SDXL_CFG_DIR, load_local_env, size_for

load_local_env()   # GPU-specific settings from the installer (local.env), before torch is imported
os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")   # flash attention on recent AMD GPUs

import torch

ROOT = Path(__file__).resolve().parent
DEV = "cuda"
NEG_CHROMA = ("low quality, ugly, unfinished, out of focus, deformed, disfigure, blurry, smudged, "
              "restricted palette, flat colors")   # from the Chroma1-HD model card
NEG_SDXL = "lowres, worst quality, low quality, blurry, jpeg artifacts, bad anatomy, bad hands, watermark, text"


def log(msg, t0=[time.time()]):
    print(f"[{time.time() - t0[0]:7.1f}s] {msg}", flush=True)


def free():
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def watch_parent():
    """Exit when the Studio server dies, so the GPU memory is released."""
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


def vram_gb():
    try:
        return torch.cuda.get_device_properties(0).total_memory / 2**30
    except Exception:
        return 0


def load_chroma(prompt, neg, cfg, offload):
    from diffusers import AutoencoderKL, ChromaPipeline, ChromaTransformer2DModel, FlowMatchEulerDiscreteScheduler
    from transformers import T5EncoderModel, T5TokenizerFast
    dt = torch.bfloat16
    if offload:   # small GPU: diffusers moves each part to the GPU only while it runs
        log("model (CPU offload)…")
        pipe = ChromaPipeline.from_pretrained(str(CHROMA_DIR), torch_dtype=dt)
        pipe.enable_model_cpu_offload()
        with torch.no_grad():
            pe, _, pm, ne, _, nm = pipe.encode_prompt(prompt, neg, device=DEV, do_classifier_free_guidance=cfg > 1.0)
        log("prompt encoded")
        return pipe, dict(prompt_embeds=pe, prompt_attention_mask=pm, negative_prompt_embeds=ne,
                          negative_prompt_attention_mask=nm)
    log("text encoder…")
    tok = T5TokenizerFast.from_pretrained(str(CHROMA_DIR / "tokenizer"))
    te = T5EncoderModel.from_pretrained(str(CHROMA_DIR / "text_encoder"), torch_dtype=dt).to(DEV)
    vae = AutoencoderKL.from_pretrained(str(CHROMA_DIR / "vae"), torch_dtype=dt).to(DEV)
    sched = FlowMatchEulerDiscreteScheduler.from_pretrained(str(CHROMA_DIR / "scheduler"))
    pipe = ChromaPipeline(scheduler=sched, vae=vae, text_encoder=te, tokenizer=tok, transformer=None)
    with torch.no_grad():
        pe, _, pm, ne, _, nm = pipe.encode_prompt(prompt, neg, device=DEV, do_classifier_free_guidance=cfg > 1.0)
    pipe.register_modules(text_encoder=None)
    del te
    free()
    log("prompt encoded")
    log("image model…")
    try:   # straight into VRAM, without a full copy in system RAM
        tr = ChromaTransformer2DModel.from_pretrained(str(CHROMA_DIR / "transformer"), torch_dtype=dt, device_map=DEV)
    except Exception:
        tr = ChromaTransformer2DModel.from_pretrained(str(CHROMA_DIR / "transformer"), torch_dtype=dt).to(DEV)
    pipe.register_modules(transformer=tr)
    free()
    return pipe, dict(prompt_embeds=pe, prompt_attention_mask=pm, negative_prompt_embeds=ne,
                      negative_prompt_attention_mask=nm)


def load_sdxl(ckpt, prompt, neg, offload):
    from diffusers import StableDiffusionXLPipeline
    log("image model…")
    pipe = StableDiffusionXLPipeline.from_single_file(str(ckpt), config=str(SDXL_CFG_DIR), torch_dtype=torch.float16,
                                                      local_files_only=True)
    pipe.vae.enable_tiling()
    if offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(DEV)
    log("text encoder…")
    with torch.no_grad():
        pe, ne, ppe, npe = pipe.encode_prompt(prompt, device=DEV, num_images_per_prompt=1,
                                              do_classifier_free_guidance=True, negative_prompt=neg)
    log("prompt encoded")
    return pipe, dict(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=ppe,
                      negative_pooled_prompt_embeds=npe)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("prompt")
    p.add_argument("--neg", default=None)
    p.add_argument("--aspect", default="1:1", choices=sorted(IMAGE_ASPECTS))
    p.add_argument("--mp", type=float, default=1.0, help="megapixels (1.0 = 1024x1024)")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--steps", type=int, default=None, help="default 30 (Chroma) / 28 (SDXL)")
    p.add_argument("--cfg", type=float, default=None, help="default 3.0 (Chroma) / 5.0 (SDXL)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--model", default="chroma", help="'chroma' or a .safetensors file in models/checkpoints")
    p.add_argument("--offload", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--out", default=None, help="output .png; with --count > 1 a _2, _3… suffix is added")
    a = p.parse_args()
    watch_parent()

    chroma = a.model == "chroma"
    if chroma and not (CHROMA_DIR / "model_index.json").exists():
        raise SystemExit("FileNotFoundError: Chroma1-HD is not downloaded – run: python download_models.py image")
    ckpt = None if chroma else CHECKPOINTS / Path(a.model).name
    if ckpt is not None and not ckpt.exists():
        raise SystemExit(f"FileNotFoundError: checkpoint not found: {ckpt}")
    steps = a.steps or (30 if chroma else 28)
    cfg = a.cfg if a.cfg is not None else (3.0 if chroma else 5.0)
    neg = a.neg or (NEG_CHROMA if chroma else NEG_SDXL)
    seed = a.seed if a.seed is not None else int.from_bytes(os.urandom(4), "little")
    w, h = size_for(a.aspect, a.mp)
    need = 22 if chroma else 10
    offload = a.offload == "on" or (a.offload == "auto" and vram_gb() < need)
    out = Path(a.out) if a.out else ROOT / "output" / f"img_{time.strftime('%Y%m%d_%H%M%S')}_{seed}.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    if chroma:
        pipe, emb = load_chroma(a.prompt, neg, cfg, offload)
    else:
        pipe, emb = load_sdxl(ckpt, a.prompt, neg, offload)
    log("models loaded")

    for i in range(a.count):
        s = seed + i
        log(f"image {i + 1}/{a.count}: {w}x{h}, {steps} steps, cfg {cfg}, seed {s}")
        with torch.no_grad():
            img = pipe(**emb, width=w, height=h, num_inference_steps=steps, guidance_scale=cfg,
                       generator=torch.Generator("cpu").manual_seed(s)).images[0]
        dst = out if a.count == 1 or i == 0 else out.with_name(f"{out.stem}_{i + 1}.png")
        tmp = dst.with_name(dst.stem + ".part.png")
        img.save(tmp)
        os.replace(tmp, dst)   # the library only ever sees finished images
        log(f"SAVED {dst.name} seed {s}")
        free()
    log(f"DONE ({a.count} image{'s' if a.count > 1 else ''})")


if __name__ == "__main__":
    main()
