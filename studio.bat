@echo off
rem Videogen Studio (desktop app). First run install.bat
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
    echo Not installed yet - run install.bat
    pause
    exit /b 1
)
if exist "studio\node_modules\electron\dist\electron.exe" (
    start "" "studio\node_modules\electron\dist\electron.exe" studio
    exit /b 0
)
rem no desktop app -> browser
echo Desktop app not installed - opening Videogen Studio in your browser. Close this window to stop.
if "%WAN_PORT%"=="" set WAN_PORT=7870
start "" /b cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%WAN_PORT%"
venv\Scripts\python.exe server.py
