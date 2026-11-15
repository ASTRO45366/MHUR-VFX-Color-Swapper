@echo off
setlocal
cd /d "%~dp0"
title Building MHUR VFX Color Swapper
echo.
echo  MHUR VFX Color Swapper - build the EXE
echo  ======================================
set "PY="
where py >nul 2>nul && py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY goto nopython
echo.
echo [1/3] Installing build tools (first time only)...
%PY% -m pip install --disable-pip-version-check -q -r requirements-build.txt
if errorlevel 1 (
  echo       Pinned versions not available, installing the latest PyInstaller instead...
  %PY% -m pip install --disable-pip-version-check -q pyinstaller
  if errorlevel 1 goto failed
)
echo [2/3] Building the EXE (takes a minute)...
set "PYINSTALLER_CONFIG_DIR=%~dp0build\pyinstaller-config"
%PY% -m PyInstaller --clean --noconfirm --log-level=WARN MHUR_VFX_Recolor.spec
if errorlevel 1 goto failed
echo [3/3] Done: dist\MHUR_VFX_Color_Swapper.exe
echo       Its data (exports, settings, game data) goes into "MHUR VFX Swapper Data" beside the EXE.
start "" explorer "%~dp0dist"
pause
exit /b 0
:nopython
echo Python was not found. Install Windows x64 Python 3.12 from https://www.python.org/downloads/
echo (tick "Add python.exe to PATH"), then run this file again.
pause
exit /b 1
:failed
echo.
echo Build failed - see the messages above.
pause
exit /b 1
