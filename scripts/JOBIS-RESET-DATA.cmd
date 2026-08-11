@echo off
setlocal
title JOBIS Local Data Reset
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0reset-local-data.ps1"
if errorlevel 1 (
  echo.
  echo JOBIS data reset failed. Review the error above.
  pause
  exit /b 1
)
echo.
pause
endlocal
