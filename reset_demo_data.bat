@echo off
cd /d "%~dp0"
echo Rebuilding the demo database (all changes you made will be lost)...
python -m backend.seed
pause
