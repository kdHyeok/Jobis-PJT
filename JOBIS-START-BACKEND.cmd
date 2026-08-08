@echo off
setlocal
title JOBIS Backend - Port 8380
echo Starting PostgreSQL if needed, then the JOBIS backend on http://localhost:8380
echo Close this window or press Ctrl+C to stop only the backend server.
echo PostgreSQL remains available for the next backend start.
echo.
powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0scripts\start-backend.ps1"
endlocal
