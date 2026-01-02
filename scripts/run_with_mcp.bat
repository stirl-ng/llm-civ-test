@echo off
REM Run Civilization V Orchestrator with MCP Server
REM
REM This script starts the orchestrator with the integrated MCP HTTP server,
REM allowing LLMs to control the game via HTTP API.

setlocal

REM Configuration
set MCP_HTTP_ENABLED=true
if "%MCP_HTTP_HOST%"=="" set MCP_HTTP_HOST=localhost
if "%MCP_HTTP_PORT%"=="" set MCP_HTTP_PORT=8765
if "%CIVV_PIPE%"=="" set CIVV_PIPE=\\.\pipe\civv_llm

REM Change to python directory
cd /d "%~dp0..\python"

REM Display configuration
echo ==========================================
echo Civ V Orchestrator with MCP Server
echo ==========================================
echo MCP HTTP Server: http://%MCP_HTTP_HOST%:%MCP_HTTP_PORT%
echo Civ V Pipe: %CIVV_PIPE%
echo ==========================================
echo.

REM Run orchestrator
python -m orchestrator %*

endlocal
