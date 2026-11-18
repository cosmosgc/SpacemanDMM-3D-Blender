@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if not errorlevel 1 goto use_py

python "%~dp0launcher.py"
goto finished

:use_py
py -3 "%~dp0launcher.py"

:finished
if errorlevel 1 (
    echo.
    echo Failed to start the DMM to Blender launcher.
    echo Make sure Python 3 with Tkinter is installed and available on PATH.
    pause
)
endlocal
