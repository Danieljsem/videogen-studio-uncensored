# Run a Python script with the ROCm environment (e.g. from WSL): powershell -File dev\run.ps1 dev\check_env.py
param([string]$script)
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:HIP_PATH="C:\Program Files\AMD\ROCm\7.1\"; $env:PATH="$($env:HIP_PATH)bin;$env:PATH"
$env:PYTORCH_ROCM_ARCH="gfx1151"; $env:HSA_OVERRIDE_GFX_VERSION="11.5.1"; $env:MIOPEN_FIND_MODE="2"; $env:MIOPEN_LOG_LEVEL="3"; $env:PYTHONUTF8="1"
& .\venv\Scripts\python.exe -u $script @args 2>&1 | ForEach-Object { "$_" }
"EXIT $LASTEXITCODE"
