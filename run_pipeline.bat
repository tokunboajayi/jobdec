@echo off
rem Runs the application loop until today's target, with output saved to logs\runner_YYYY-MM-DD.log.
rem Task Scheduler runs this every morning (task "jobdec daily").
cd /d %~dp0
if not exist logs mkdir logs
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set D=%%d
python -u run_until_target.py %* >> "logs\runner_%D%.log" 2>&1
