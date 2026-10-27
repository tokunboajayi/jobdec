@echo off
cd /d %~dp0
echo === Running Headless Autonomous Application Pipeline ===
python batch_apply_parallel.py --workers 1 %*
pause
