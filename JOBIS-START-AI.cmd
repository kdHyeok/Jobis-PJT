@echo off
setlocal
title JOBIS AI - Port 8400
echo Starting the unified JOBIS AI on http://127.0.0.1:8400
echo Close this window or press Ctrl+C to stop only the AI server.
echo.
powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start-ai-agent.ps1"
endlocal
