@echo off
cd /d %~dp0
echo === AJ daily run: inbox - new jobs - scout - apply - fix - outreach drafts - briefing ===
python -u daily_run.py %* >> daily_run.log 2>&1
type briefings\%date:~-4%-%date:~4,2%-%date:~7,2%.md 2>nul
