@echo off
cd /d %~dp0
if "%~1"=="" (set /p URL=Paste the application URL: ) else (set URL=%~1)
python fill.py "%URL%" %2 %3 %4 %5 %6 %7 %8
pause
