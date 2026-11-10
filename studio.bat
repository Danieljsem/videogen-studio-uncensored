@echo off
rem Videogen Studio (desktop app). First run: cd studio && npm install
cd /d "%~dp0studio"
if not exist "node_modules\electron\dist\electron.exe" (
    echo Electron is not installed. Run: cd studio ^&^& npm install
    pause
    exit /b 1
)
start "" "node_modules\electron\dist\electron.exe" .
