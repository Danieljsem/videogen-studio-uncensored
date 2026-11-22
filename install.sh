#!/usr/bin/env bash
# Videogen Studio installer for Linux (x86_64).   ./install.sh [options]
#
#   --gpu auto|nvidia|amd|cpu   which PyTorch build to install (default: detected)
#   --torch-index URL           use a specific PyTorch wheel index instead
#   --models video,image|none   which models to download now (default: ask; "none" = later, from the app)
#   --yes                       no questions (models: none unless --models is given)
#
# Everything goes into this folder (venv/, tools/, models/). Nothing is installed system-wide, no sudo.
# Safe to run again: finished steps are skipped, interrupted model downloads resume.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
ROOT="$PWD"
ELECTRON_VERSION=33.4.11
ELECTRON_SHA=212d431c7c916292311c797cd91f84467c5abd6e6983cf24b162efff64cee8a9
GPU=auto; TORCH_INDEX=""; MODELS=""; YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --gpu) GPU="$2"; shift 2 ;;
    --torch-index) TORCH_INDEX="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --yes|-y) YES=1; shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done

c() { printf '\033[%sm%s\033[0m\n' "$1" "$2"; }
step() { echo; c "1;36" "[$1/6] $2"; }
ok() { c 32 "      $1"; }
info() { c 90 "      $1"; }
warn() { c 33 "      $1"; }
fail() { echo; c 31 "ERROR: $1"; exit 1; }
fetch() { if command -v curl >/dev/null; then curl -fsSL "$1" -o "$2"; else wget -q "$1" -O "$2"; fi; }

echo
c 1 "  Videogen Studio installer"
c 90 "  local image -> video (Wan 2.2) and text -> image (Chroma), no cloud"
[ "$(uname -m)" = x86_64 ] || fail "only x86_64 Linux is supported."

# ---------------------------------------------------------------- 1. uv + Python
step 1 "Python 3.12 (private copy in this folder)"
export UV_PYTHON_INSTALL_DIR="$ROOT/tools/python"
UV="$ROOT/tools/uv"
if [ ! -x "$UV" ]; then
  if command -v uv >/dev/null; then UV="$(command -v uv)"
  else
    info "downloading uv (Python package manager)..."
    fetch https://astral.sh/uv/install.sh /tmp/uv-install-$$.sh
    env UV_INSTALL_DIR="$ROOT/tools" UV_NO_MODIFY_PATH=1 sh /tmp/uv-install-$$.sh >/dev/null
    rm -f /tmp/uv-install-$$.sh
    [ -x "$UV" ] || fail "uv could not be installed. Check your internet connection."
  fi
fi
PY="$ROOT/venv/bin/python"
[ -x "$PY" ] || "$UV" venv --python 3.12 venv || fail "could not create the Python environment."
ok "Python ready"

# ---------------------------------------------------------------- 2. GPU + PyTorch
step 2 "PyTorch for your graphics card"
GPUS="$(lspci 2>/dev/null | grep -iE 'vga|3d|display' | sed 's/^[^:]*: //' || true)"
[ -n "$GPUS" ] && info "found: $(echo "$GPUS" | paste -sd ';' -)"
if [ "$GPU" = auto ]; then
  if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then GPU=nvidia
  elif [ -e /dev/kfd ] || echo "$GPUS" | grep -qiE 'amd|ati|radeon'; then GPU=amd
  else GPU=cpu; fi
fi
ENV_LINES="# written by install.sh - GPU settings for Videogen Studio (KEY=VALUE, environment variables win)"
if [ -z "$TORCH_INDEX" ]; then
  case "$GPU" in
    nvidia)
      # CUDA 13 wheels need driver 580+, CUDA 12.8 needs 570+; older drivers get CUDA 12.6
      DRV="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 | cut -d. -f1)"
      DRV="${DRV:-0}"
      if [ "$DRV" -ge 580 ] || [ "$DRV" -eq 0 ]; then TORCH_INDEX=https://download.pytorch.org/whl/cu130
      elif [ "$DRV" -ge 570 ]; then TORCH_INDEX=https://download.pytorch.org/whl/cu128
      else TORCH_INDEX=https://download.pytorch.org/whl/cu126; warn "NVIDIA driver $DRV is old - consider updating to 580+ for the newest PyTorch."; fi
      ;;
    amd)
      TORCH_INDEX=https://download.pytorch.org/whl/rocm7.2
      ENV_LINES="$ENV_LINES
TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1"
      [ -e /dev/kfd ] || warn "/dev/kfd is missing - the amdgpu kernel driver is not loaded, ROCm will not see the GPU."
      if [ -e /dev/kfd ] && ! [ -r /dev/kfd ] ; then warn "no access to /dev/kfd - run: sudo usermod -aG render,video \$USER  (then log out and in)"; fi
      ;;
    *) warn "no NVIDIA or AMD GPU found - installing the CPU build. The app opens, but generating needs a GPU."
       TORCH_INDEX=https://download.pytorch.org/whl/cpu ;;
  esac
fi
if "$PY" -c "import torch" >/dev/null 2>&1; then
  ok "PyTorch already installed - keeping it"
else
  info "installing PyTorch from $TORCH_INDEX (about 3-5 GB)..."
  "$UV" pip install --python "$PY" --index-url "$TORCH_INDEX" torch || fail "PyTorch install failed. Try again, or pass --torch-index URL."
  ok "PyTorch installed"
fi
[ -f local.env ] || printf '%s\n' "$ENV_LINES" > local.env

# ---------------------------------------------------------------- 3. Python packages
step 3 "Python packages (diffusers, transformers, ...)"
"$UV" pip install --python "$PY" -r requirements.txt || fail "package install failed."
ok "packages installed"

# ---------------------------------------------------------------- 4. check the GPU
step 4 "Checking the GPU"
RES="$("$PY" - 2>/dev/null <<'PYEOF' | tail -1 || true
import torch
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    print(f"OK {p.total_memory / 2**30:.0f} {p.name}")
else:
    print("NOGPU")
PYEOF
)"
if [ "${RES%% *}" = OK ]; then
  MEM="$(echo "$RES" | cut -d' ' -f2)"; NAME="$(echo "$RES" | cut -d' ' -f3-)"
  ok "GPU: $NAME, $MEM GB"
  if [ "$MEM" -lt 22 ]; then warn "Image generation runs with CPU offload (slower). Video (Wan 2.2 A14B) needs ~64 GB of GPU memory."
  elif [ "$MEM" -lt 60 ]; then warn "Image generation: fine. Video (Wan 2.2 A14B) needs ~64 GB of GPU memory and will likely run out of memory."; fi
else
  warn "PyTorch does not see a GPU. The app will start, but generation will fail. See README > Troubleshooting."
fi

# ---------------------------------------------------------------- 5. desktop app (Electron, no Node.js needed)
step 5 "Desktop app"
DIST="$ROOT/studio/node_modules/electron/dist"
if [ -x "$DIST/electron" ]; then ok "already installed"
else
  ZIP="/tmp/electron-v$ELECTRON_VERSION-linux-x64-$$.zip"
  info "downloading Electron $ELECTRON_VERSION (~105 MB)..."
  fetch "https://github.com/electron/electron/releases/download/v$ELECTRON_VERSION/electron-v$ELECTRON_VERSION-linux-x64.zip" "$ZIP" \
    || fail "Electron download failed."
  echo "$ELECTRON_SHA  $ZIP" | sha256sum -c --status || { rm -f "$ZIP"; fail "Electron download is corrupted (checksum mismatch). Run the installer again."; }
  TMP="$DIST.tmp"   # extract next to it first, so an interrupted install never looks finished
  rm -rf "$TMP"; mkdir -p "$TMP"
  if command -v unzip >/dev/null; then unzip -qo "$ZIP" -d "$TMP"; else "$PY" -m zipfile -e "$ZIP" "$TMP"; fi
  chmod +x "$TMP/electron" "$TMP/chrome_crashpad_handler" 2>/dev/null || true
  rm -rf "$DIST"; mkdir -p "$(dirname "$DIST")"; mv "$TMP" "$DIST"
  rm -f "$ZIP"
  ok "installed"
fi
chmod +x studio.sh generate.sh 2>/dev/null || true   # in case the files lost their exec bit (ZIP download)
DESK="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESK"
cat > "$DESK/videogen-studio.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Videogen Studio
Comment=Local image-to-video and text-to-image
Exec="$ROOT/studio.sh"
Icon=$ROOT/studio/icon.png
Terminal=false
Categories=Graphics;Video;
DESKTOP
ok "added to the application menu"

# ---------------------------------------------------------------- 6. models
step 6 "Models"
if [ -z "$MODELS" ]; then
  if [ "$YES" = 1 ] || [ ! -t 0 ]; then MODELS=none
  else
    echo "      What should be downloaded now? (you can also do it later inside the app)"
    echo "        1  Image model  Chroma1-HD       27.5 GB   needs ~24 GB GPU memory (less with offload)"
    echo "        2  Video model  Wan 2.2 A14B     71 GB     needs ~64 GB GPU memory"
    echo "        3  Both                          99 GB"
    echo "        4  Later, from the app"
    read -rp "      Choice [4]: " CH
    case "$CH" in 1) MODELS=image ;; 2) MODELS=video ;; 3) MODELS=image,video ;; *) MODELS=none ;; esac
  fi
fi
if [ "$MODELS" != none ]; then
  # shellcheck disable=SC2046
  "$PY" download_models.py $(echo "$MODELS" | tr ',' ' ') \
    || warn "Download did not finish. Run ./install.sh again or use the Download button in the app - it resumes."
else
  info "skipped - the app offers the download when you open Create image / Create video"
fi

echo
c 32 "  Done. Start Videogen Studio from the application menu or with ./studio.sh"
echo
