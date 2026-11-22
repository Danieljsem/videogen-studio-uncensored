@echo off
title Videogen Studio - text to image
cd /d "%~dp0"
REM Usage: generate_image.bat "prompt" [--aspect 16:9] [--count 4] [--steps 30] [--model chroma]
REM GPU settings come from local.env (written by install.bat).
set PYTHONUTF8=1
if not "%~1"=="" goto args
set /p PROMPT=Describe the image (English works best): 
venv\Scripts\python.exe generate_image.py "%PROMPT%"
goto end
:args
venv\Scripts\python.exe generate_image.py %*
:end
pause
