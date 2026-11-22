@echo off
title Videogen Studio - image to video
cd /d "%~dp0"
REM Usage: drag an image onto this file, or: generate.bat image.jpg "prompt" [--res 720] [--sec 5]
REM GPU settings come from local.env (written by install.bat).
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
