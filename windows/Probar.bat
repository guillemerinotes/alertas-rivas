@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%LOCALAPPDATA%\AlertasRivas\probar.ps1"
if errorlevel 1 pause
timeout /t 8
