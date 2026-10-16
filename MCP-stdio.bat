@echo off
rem Used by MCP clients (opencode/antigravity). Do not double-click.
rem Stdout must stay clean JSON-RPC only.
cd /d "%~dp0"
python -m src.server.mcp_server --transport stdio
