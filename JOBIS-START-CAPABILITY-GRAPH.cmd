@echo off
setlocal
title JOBIS Capability Graph - Port 8600
echo Starting the optional Capability Graph HTTP compatibility facade on http://127.0.0.1:8600
echo The normal JOBIS AI launch does not require this process.
echo Close this window or press Ctrl+C to stop only this facade.
echo.
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start-capability-graph.ps1"
endlocal
