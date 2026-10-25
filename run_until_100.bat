@echo off
cd /d %~dp0
python -u run_until_target.py %*
pause
