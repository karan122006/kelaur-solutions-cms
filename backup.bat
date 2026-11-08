@echo off
cd /d "%~dp0"
python -m backend.backup
echo Backups are kept in the data\backups folder (newest 14).
pause
