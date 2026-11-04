@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 MHUR_VFX_Recolor.py & goto :eof)
where python >nul 2>nul && (python MHUR_VFX_Recolor.py & goto :eof)
echo Python 3.9+ is required. Install it from https://www.python.org/downloads/ (tick "Add to PATH").
pause
