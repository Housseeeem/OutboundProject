@echo off
set DANGEROUSLY_OMIT_AUTH=true

npx -y @modelcontextprotocol/inspector ..\..\venv\Scripts\python mcp_server.py