@echo off
"%~dp0.venv\Scripts\python.exe" -m vessel %*
exit /b %errorlevel%
