@echo off
cd /d %~dp0
echo ==============================================================
echo   AJ PARALLEL APPLICATOR: TARGET 300 MILESTONE RUNNER
echo   Concurrent Workers: 3 Isolated Headless Browsers
echo   Asset Blocker: Active (3x Speedup)
echo ==============================================================
python -u run_until_target.py --target 300 --workers 3 %*
pause
