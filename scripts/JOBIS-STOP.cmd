@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-all.ps1"
if errorlevel 1 (
  echo.
  echo JOBIS failed to stop cleanly. Review the error above.
  pause
)
endlocal
