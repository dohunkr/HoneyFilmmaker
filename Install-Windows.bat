@echo off
title HoneyFilmmaker one-click install
cd /d "%~dp0"

echo ===============================================
echo  HoneyFilmmaker one-click install
echo  Just double-click, wait, done.
echo ===============================================
echo(

python --version >nul 2>&1
if errorlevel 1 goto :nopython
echo [1/4] Python OK
python --version
goto :deps

:nopython
echo [1/4] No Python found. Installing automatically...
winget install -e --id Python.3.11 --accept-source-agreements --accept-package-agreements
if errorlevel 1 goto :pyfail
echo Python installed. Close this window and run install again.
pause
exit /b 0

:pyfail
echo(
echo [ERROR] Auto-install failed.
echo Install Python manually: https://www.python.org/downloads/
echo Tick "Add python.exe to PATH" during setup, then run this again.
pause
exit /b 1

:deps
echo(
echo [2/4] Preparing files...
pip install -r requirements.txt
if errorlevel 1 goto :pipfail
goto :envcfg

:pipfail
echo [ERROR] pip failed. Check internet and run again.
pause
exit /b 1

:envcfg
echo(
echo [3/4] Creating config...
if not exist ".env" copy ".env.example" ".env" >nul
echo .env ready
goto :test

:test
echo(
echo [4/4] Smoke test...
python -m unittest tests.test_phase1.TestServerBoot tests.test_phase2 -v
if errorlevel 1 goto :testfail
echo(
echo ===============================================
echo  INSTALL COMPLETE!
echo  Next: double-click Start-HoneyFilmmaker.bat
echo  Then: double-click Setup-MCP.bat
echo  Guide: FRIEND-START-HERE.md
echo ===============================================
pause
exit /b 0

:testfail
echo(
echo [ERROR] Test failed. Screenshot this window and send it to your friend.
pause
exit /b 1
