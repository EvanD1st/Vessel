@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0test-all.ps1"
exit /b %errorlevel%
