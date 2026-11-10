"""Smoke test: library versions, GPU, VAE and UMT5 text encoder (no 14B models needed)."""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root
import sys, torch, diffusers, transformers, peft
print(sys.version.split()[0], torch.__version__, diffusers.__version__, transformers.__version__, peft.__version__)
print("GPU:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "-")
import generate as g
from diffusers import AutoencoderKLWan
vae = AutoencoderKLWan.from_single_file(str(g.M/"vae"/"wan_2.1_vae.safetensors"), config=str(g.CFG), subfolder="vae", torch_dtype=torch.float32)
print("VAE OK", sum(p.numel() for p in vae.parameters())/1e6, "M")
te = g.load_text_encoder()
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained(g.CFG/"tokenizer")
ids = tok(["a woman smiles"], return_tensors="pt")
with torch.no_grad(): o = te(ids.input_ids, attention_mask=ids.attention_mask).last_hidden_state
print("TE OK", o.shape, float(o.float().std()))
