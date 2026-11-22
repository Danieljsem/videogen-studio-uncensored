@echo off
rem Videogen Studio installer - double-click to run. Options are passed to install.ps1 (see the top of that file).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
