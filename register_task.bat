@echo off
cd /d "%~dp0"
echo Registering daily task at 08:00 ...
schtasks /Create /F /SC DAILY /ST 08:00 /TN "LitDaily" /TR "\"%~dp0run_silent.bat\""
if %ERRORLEVEL%==0 (
  echo OK. Task name: LitDaily
  echo Delete with: schtasks /Delete /TN "LitDaily" /F
) else (
  echo Failed. Right-click this file and choose "Run as administrator".
)
pause
