@echo off
setlocal
title JOBIS Capability Graph - Port 8600
echo Starting JOBIS Capability Graph on http://127.0.0.1:8600
echo Close this window or press Ctrl+C to stop only the Capability Graph.
echo.
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start-capability-graph.ps1"
endlocal
