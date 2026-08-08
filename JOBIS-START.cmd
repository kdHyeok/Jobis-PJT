@echo off
setlocal
title JOBIS Launcher
echo Opening dedicated log windows for Capability Graph, JOBIS AI, backend, and frontend...
start "" "%~dp0JOBIS-START-CAPABILITY-GRAPH.cmd"
start "" "%~dp0JOBIS-START-AI.cmd"
start "" "%~dp0JOBIS-START-BACKEND.cmd"
start "" "%~dp0JOBIS-START-FRONTEND.cmd"
echo.
echo Four JOBIS service windows were opened.
endlocal
