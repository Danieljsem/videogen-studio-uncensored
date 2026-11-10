@echo off
title Wan 2.2 I2V
cd /d "%~dp0"
REM Usage: drag an image onto this file, or: generate.bat image.jpg "prompt" [--res 720] [--sec 5]

set "HIP_PATH=C:\Program Files\AMD\ROCm\7.1\"
set "PATH=%HIP_PATH%bin;%PATH%"
set PYTORCH_ROCM_ARCH=gfx1151
set HSA_OVERRIDE_GFX_VERSION=11.5.1
set MIOPEN_FIND_MODE=2
set MIOPEN_LOG_LEVEL=3
set PYTHONUTF8=1

if "%~1"=="" (
    echo Drag an image onto generate.bat
    pause
    exit /b 1
)
if not "%~2"=="" goto args
set /p PROMPT=Prompt (English works best): 
venv\Scripts\python.exe generate.py "%~1" "%PROMPT%"
goto end
:args
venv\Scripts\python.exe generate.py %*
:end
pause
