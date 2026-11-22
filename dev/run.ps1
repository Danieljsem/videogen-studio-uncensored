# Run a Python script with the app's GPU settings (e.g. from WSL): powershell -File dev\run.ps1 dev\check_env.py
# The generators read local.env themselves; this only adds quieter MIOpen logging and UTF-8 output.
param([string]$script)
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:MIOPEN_FIND_MODE = "2"; $env:MIOPEN_LOG_LEVEL = "3"; $env:PYTHONUTF8 = "1"
& .\venv\Scripts\python.exe -u $script @args 2>&1 | ForEach-Object { "$_" }
"EXIT $LASTEXITCODE"
