#!/bin/bash

# Run Civilization V Orchestrator with MCP Server
#
# This script starts the orchestrator with the integrated MCP HTTP server,
# allowing LLMs to control the game via HTTP API.

set -e

# Configuration
MCP_HTTP_ENABLED=true
MCP_HTTP_HOST=${MCP_HTTP_HOST:-localhost}
MCP_HTTP_PORT=${MCP_HTTP_PORT:-8765}
CIVV_PIPE=${CIVV_PIPE:-'\\\\.\\pipe\\civv_llm'}

# Change to python directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$SCRIPT_DIR/../python"
cd "$PYTHON_DIR"

# Display configuration
echo "=========================================="
echo "Civ V Orchestrator with MCP Server"
echo "=========================================="
echo "MCP HTTP Server: http://$MCP_HTTP_HOST:$MCP_HTTP_PORT"
echo "Civ V Pipe: $CIVV_PIPE"
echo "=========================================="
echo ""

# Export environment variables
export MCP_HTTP_ENABLED
export MCP_HTTP_HOST
export MCP_HTTP_PORT
export CIVV_PIPE

# Run orchestrator
python -m orchestrator "$@"
