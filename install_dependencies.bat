@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo SpacemanDMM 3D Maps - dependency setup
echo ======================================
echo This project uses Python's standard library; there are no pip packages to install.
echo Required: Python 3.10+ and Blender 3.6+.
echo.

where winget >nul 2>nul
if errorlevel 1 (
    echo ERROR: winget is unavailable.
    echo Install or update "App Installer" from the Microsoft Store, then run this file again.
    echo You can also install Python 3.10+ and Blender 3.6+ manually.
    goto :failed
)

py -3.12 --version >nul 2>nul
if errorlevel 1 (
    echo Installing Python 3.12...
    winget install --id Python.Python.3.12 --exact --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :failed
)

rem winget may have installed Python just now; try the Python launcher again.
py -3.12 --version >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.10+ was not found after installation.
    echo Close this window, reopen a terminal so PATH can refresh, then run this file again.
    goto :failed
)

set "BLENDER="
for /f "usebackq delims=" %%B in (`py -3.12 -c "import launcher; print(launcher.find_blender())" 2^>nul`) do set "BLENDER=%%B"
if not defined BLENDER (
    echo Installing Blender...
    winget install --id BlenderFoundation.Blender --exact --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :failed
)

echo.
echo Dependency check:
py -3.12 --version
if defined BLENDER (
    echo Blender: %BLENDER%
) else (
    echo Blender was installed. If it is not detected, select blender.exe in the launcher.
)
echo.
echo Setup complete. Run run_launcher.bat to start the map picker.
echo For the browser viewer, internet access is needed for Three.js from jsDelivr.
pause
exit /b 0

:failed
echo.
echo Setup did not complete. Install Python 3.10+ and Blender 3.6+ manually,
echo or fix the error above and run install_dependencies.bat again.
pause
exit /b 1
