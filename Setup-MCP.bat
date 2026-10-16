@echo off
title MCP connect (opencode/antigravity)
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0Setup-MCP.ps1"
pause
