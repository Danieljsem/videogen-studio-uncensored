"""Model packs that Videogen Studio can download: what they contain and whether they are installed.

Used by download_models.py (the installer and the in-app "Download" button) and by server.py (status in the UI).
Standard library only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
M = ROOT / "models"

WAN = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged"
WAN_CFG = "Wan-AI/Wan2.2-I2V-A14B-Diffusers"
CHROMA = "lodestones/Chroma1-HD"
SDXL_CFG = "stabilityai/stable-diffusion-xl-base-1.0"

CHROMA_DIR = M / "image" / "chroma1-hd"
SDXL_CFG_DIR = M / "image" / "sdxl-config"
CHECKPOINTS = M / "checkpoints"          # your own SDXL .safetensors (Pony, Illustrious, … fine-tunes)

# Each pack: "files" = single files (repo, path in repo, local target), "snapshots" = (repo, allow patterns, local dir).
PACKS = {
    "video": {
        "name": "Wan 2.2 I2V A14B",
        "license": "Apache-2.0",
        "vram_gb": 64,
        "files": [
            (WAN, "split_files/diffusion_models/wan2.2_i2v_high_noise_14B_fp16.safetensors", "diffusion_models"),
            (WAN, "split_files/diffusion_models/wan2.2_i2v_low_noise_14B_fp16.safetensors", "diffusion_models"),
            (WAN, "split_files/text_encoders/umt5_xxl_fp16.safetensors", "text_encoders"),
            (WAN, "split_files/vae/wan_2.1_vae.safetensors", "vae"),
            (WAN, "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "loras"),
            (WAN, "split_files/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors", "loras"),
        ],
        # configs + tokenizer only, no weights (the weights come from the single files above)
        "snapshots": [(WAN_CFG, ["*.json", "tokenizer/*"], "diffusers-config")],
        "size_gb": 71.2,
    },
    "image": {
        "name": "Chroma1-HD",
        "license": "Apache-2.0",
        "vram_gb": 24,
        "files": [],
        "snapshots": [
            (CHROMA, ["model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*", "transformer/*", "vae/*"],
             "image/chroma1-hd"),
        ],
        "size_gb": 27.5,
    },
    # configs + tokenizers only (a few MB, no weights) so your own SDXL checkpoints in models/checkpoints load offline
    "sdxl": {
        "name": "SDXL configs",
        "license": "CreativeML Open RAIL++-M",
        "vram_gb": 10,
        "files": [],
        "snapshots": [(SDXL_CFG, ["model_index.json", "*/config.json", "scheduler/*", "tokenizer/*", "tokenizer_2/*"],
                       "image/sdxl-config")],
        "size_gb": 0.01,
    },
}


IMAGE_ASPECTS = {"1:1": (1, 1), "16:9": (16, 9), "9:16": (9, 16), "3:2": (3, 2), "2:3": (2, 3), "4:5": (4, 5),
                 "5:4": (5, 4)}


def size_for(aspect, mp=1.0, mod=64):
    """Image width/height with ~mp megapixels (1.0 = 1024x1024) for the aspect ratio, multiples of 64."""
    a, b = IMAGE_ASPECTS[aspect]
    area = mp * 1024 * 1024
    return round((area * a / b) ** 0.5 / mod) * mod, round((area * b / a) ** 0.5 / mod) * mod


def _required(pack):
    p = PACKS[pack]
    req = [M / sub / Path(path).name for _, path, sub in p["files"]]
    if pack == "video":
        req += [M / "diffusers-config" / "model_index.json", M / "diffusers-config" / "tokenizer" / "tokenizer_config.json"]
    if pack == "image":
        req += [CHROMA_DIR / "model_index.json", CHROMA_DIR / "transformer" / "diffusion_pytorch_model.safetensors.index.json",
                CHROMA_DIR / "text_encoder" / "model.safetensors.index.json", CHROMA_DIR / "vae" / "config.json"]
    if pack == "sdxl":
        req += [SDXL_CFG_DIR / "model_index.json", SDXL_CFG_DIR / "unet" / "config.json",
                SDXL_CFG_DIR / "tokenizer_2" / "vocab.json"]
    return req


def installed(pack):
    """True when every file the generator needs is on disk (a finished download writes them last)."""
    ok = all(f.exists() for f in _required(pack))
    if ok and pack == "image":   # sharded weights: every shard listed in the index must exist
        import json
        for sub, idx in (("transformer", "diffusion_pytorch_model.safetensors.index.json"),
                         ("text_encoder", "model.safetensors.index.json")):
            try:
                shards = set(json.loads((CHROMA_DIR / sub / idx).read_text("utf-8"))["weight_map"].values())
            except Exception:
                return False
            if not all((CHROMA_DIR / sub / s).exists() for s in shards):
                return False
    return ok


def sdxl_checkpoints():
    """Your own SDXL checkpoints (single .safetensors files) in models/checkpoints."""
    if not CHECKPOINTS.exists():
        return []
    return sorted(f.name for f in CHECKPOINTS.glob("*.safetensors"))


def image_models():
    """Image models the UI can offer: the built-in Chroma (when downloaded) + SDXL checkpoints (need the configs)."""
    out = []
    if installed("image"):
        out.append({"id": "chroma", "name": "Chroma1-HD", "kind": "chroma"})
    if installed("sdxl"):
        out += [{"id": f, "name": Path(f).stem.replace("_", " "), "kind": "sdxl"} for f in sdxl_checkpoints()]
    return out


def load_local_env():
    """Apply local.env (written by the installer: GPU-specific variables such as ROCm settings).

    KEY=VALUE per line, # comments. Variables already set in the environment win. Call before importing torch.
    """
    import os
    f = ROOT / "local.env"
    if not f.exists():
        return
    for line in f.read_text("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
    hip = os.environ.get("HIP_PATH")
    if hip and os.name == "nt" and Path(hip, "bin").is_dir() and str(Path(hip, "bin")) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(Path(hip, "bin")) + os.pathsep + os.environ.get("PATH", "")
