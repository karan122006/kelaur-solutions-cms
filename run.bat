@echo off
title Sunrise Family Clinics CMS (Keluar Solutions)
cd /d "%~dp0"
echo Installing Flask (first run only)...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo.
  echo Python was not found. Install Python 3.10+ from https://www.python.org and tick "Add to PATH".
  pause
  exit /b
)
start "" http://127.0.0.1:5000
python app.py
pause
