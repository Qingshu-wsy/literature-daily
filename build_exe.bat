@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing build dependencies...
    python -m pip install -r requirements-build.txt
    if errorlevel 1 goto failed
)

echo Building the GUI application (folder version)...
python -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name "文献日报" ^
  --distpath "build\release" ^
  --workpath "build\pyinstaller" ^
  --icon "文献.ico" ^
  --collect-all PySide6.QtWebEngineCore ^
  --collect-all PySide6.QtWebEngineWidgets ^
  --collect-all shiboken6 ^
  gui.py
if errorlevel 1 goto failed

set "APP_DIR=%~dp0dist\文献日报"
set "STAGED_DIR=%~dp0build\release\文献日报"
if not exist "%APP_DIR%" mkdir "%APP_DIR%"
if errorlevel 1 goto failed
robocopy "%STAGED_DIR%\_internal" "%APP_DIR%\_internal" /MIR /NFL /NDL /NJH /NJS /NC /NS
if errorlevel 8 goto failed
copy /y "%STAGED_DIR%\文献日报.exe" "%APP_DIR%\文献日报.exe" >nul
if errorlevel 1 goto failed
if not exist "%APP_DIR%\config.yaml" copy /y "%~dp0config.yaml" "%APP_DIR%\config.yaml" >nul
if errorlevel 1 goto failed
if not exist "%APP_DIR%\secrets.example.yaml" copy /y "%~dp0secrets.example.yaml" "%APP_DIR%\secrets.example.yaml" >nul
if errorlevel 1 goto failed
copy /y "%~dp0README.md" "%APP_DIR%\README.md" >nul
if errorlevel 1 goto failed
copy /y "%~dp0README.en.md" "%APP_DIR%\README.en.md" >nul
if errorlevel 1 goto failed
copy /y "%~dp0文献.ico" "%APP_DIR%\文献.ico" >nul
if errorlevel 1 goto failed

echo.
echo Building the single-file GUI application...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "文献日报" ^
  --distpath "build\release-single" ^
  --workpath "build\pyinstaller-single" ^
  --icon "文献.ico" ^
  --collect-all PySide6.QtWebEngineCore ^
  --collect-all PySide6.QtWebEngineWidgets ^
  --collect-all shiboken6 ^
  gui.py
if errorlevel 1 goto failed

set "SINGLE_DIR=%~dp0dist\文献日报单文件"
set "SINGLE_EXE=%~dp0build\release-single\文献日报.exe"
if not exist "%SINGLE_DIR%" mkdir "%SINGLE_DIR%"
if errorlevel 1 goto failed
copy /y "%SINGLE_EXE%" "%SINGLE_DIR%\文献日报.exe" >nul
if errorlevel 1 goto failed
if not exist "%SINGLE_DIR%\config.yaml" copy /y "%~dp0config.yaml" "%SINGLE_DIR%\config.yaml" >nul
if errorlevel 1 goto failed
if not exist "%SINGLE_DIR%\secrets.example.yaml" copy /y "%~dp0secrets.example.yaml" "%SINGLE_DIR%\secrets.example.yaml" >nul
if errorlevel 1 goto failed
copy /y "%~dp0README.md" "%SINGLE_DIR%\README.md" >nul
if errorlevel 1 goto failed
copy /y "%~dp0README.en.md" "%SINGLE_DIR%\README.en.md" >nul
if errorlevel 1 goto failed
copy /y "%~dp0文献.ico" "%SINGLE_DIR%\文献.ico" >nul
if errorlevel 1 goto failed

echo.
echo Build succeeded:
echo   %APP_DIR%\文献日报.exe
echo   %SINGLE_DIR%\文献日报.exe
echo The first is a folder version; the second runs without an _internal folder.
echo Keep config.yaml and other data next to the single-file EXE.
echo Your secrets.yaml is not bundled. Create it from secrets.example.yaml or use the GUI.
pause
exit /b 0

:failed
echo.
echo Build failed. Review the messages above.
pause
exit /b 1
