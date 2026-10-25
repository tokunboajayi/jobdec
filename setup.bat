@echo off
cd /d %~dp0
echo === AJ Autofill setup (one time) ===
python --version >nul 2>&1 || (echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
python -m pip install --upgrade pip playwright
python -m playwright install chromium
echo.
echo Setup done. To apply:  apply.bat "https://application-url"
pause
