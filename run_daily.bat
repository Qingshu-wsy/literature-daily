@echo off
cd /d "%~dp0"
echo ============================================
echo   Daily literature screening
echo ============================================
python run_daily.py %*
set RC=%ERRORLEVEL%
echo.
if not "%RC%"=="0" echo [ERROR] exit code %RC% - see messages above.
if not "%RC%"=="0" echo If this window closes too fast, run: python run_daily.py
echo Done. Report: out\daily\latest.html
if "%~1"=="" pause
