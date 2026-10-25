@echo off
cd /d %~dp0
echo === Running Headless Autonomous Application Pipeline ===
python batch_apply.py %*
pause
