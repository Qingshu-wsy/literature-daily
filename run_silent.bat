@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
python run_daily.py --no-open >> logs\run.log 2>&1
