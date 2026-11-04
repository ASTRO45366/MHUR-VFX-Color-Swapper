@echo off
setlocal
cd /d "%~dp0"
set "PYINSTALLER_CONFIG_DIR=%~dp0build\pyinstaller-config"
py -3.12 -m PyInstaller --clean --noconfirm MHUR_VFX_Recolor.spec
if errorlevel 1 goto failed
echo Done: dist\MHUR_VFX_Color_Swapper.exe
exit /b 0
:failed
echo Build failed. Install Windows x64 Python 3.12 and run py -3.12 -m pip install -r requirements-build.txt.
exit /b 1
