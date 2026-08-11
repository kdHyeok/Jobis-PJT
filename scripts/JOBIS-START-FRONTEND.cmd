@echo off
setlocal
title JOBIS Frontend - Port 5473
echo Starting the JOBIS frontend on http://localhost:5473
echo Close this window or press Ctrl+C to stop only the frontend server.
echo.
powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%~dp0start-frontend.ps1"
endlocal
