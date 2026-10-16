@echo off
title HoneyFilmmaker server
cd /d "%~dp0"

echo Starting HoneyFilmmaker server...
echo URL: http://127.0.0.1:8765/health
echo Keep this window open. Close it to stop the server.
echo(
python scripts\run_server.py --transport http --port 8765
echo(
echo [ERROR] Server stopped. Run Install-Windows.bat first.
pause
