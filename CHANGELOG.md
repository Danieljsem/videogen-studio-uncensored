# Changelog

## 2.0.0 – 2026-11-22

### New
- **Text → image** with [Chroma1-HD](https://huggingface.co/lodestones/Chroma1-HD) (8.9B, Apache 2.0, uncensored): 7 aspect ratios, 1 or 1.5 MP, batches of 1/2/4, steps, CFG, seed, negative prompt, style chips.
- **Your own SDXL checkpoints** from `models/checkpoints/` (only 5 MB of configs are downloaded once).
- **Animate**: turn any generated image into the input of a video with one click.
- **One-click installers** for Windows (`install.bat`) and Linux (`install.sh`): private Python 3.12 via uv, PyTorch picked for your GPU (CUDA 13, ROCm 7.2 on Linux, AMD TheRock builds on Windows, CPU fallback), GPU memory check, checksum-verified Electron (no Node.js needed), desktop / app-menu shortcut, optional model download. Safe to re-run.
- **Model downloads inside the app** with progress, stop and resume (`download_models.py` on the command line).
- **Linux support** for the desktop app, launchers (`studio.sh`, `generate.sh`) and the server.
- Library shows videos and images, with an All / Videos / Images filter.

### Changed
- GPU-specific environment variables now live in `local.env` (written by the installer) instead of being hard-coded for one AMD GPU.
- The app starts in the browser when the desktop shell isn't installed.
- Elements hidden by the UI now stay hidden (some buttons with their own layout ignored the `hidden` attribute).

### Unchanged
- The Wan 2.2 video pipeline, its settings and the library format: 1.x videos show up as before.

## 1.0 – 2026-11-10

First public release: Wan 2.2 A14B image → video desktop app, 480p/720p, 5–15 s, LoRAs, queue with time estimates, crash-safe partial videos, UI in 5 languages.
