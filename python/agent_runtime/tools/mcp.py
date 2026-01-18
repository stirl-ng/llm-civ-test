from __future__ import annotations

from typing import Any, Dict

import requests

from .base import Tool


class MCPClientTool(Tool):
    """HTTP client for orchestrator tools."""

    def __init__(self, base_url: str = "http://localhost:8765"):
        self.base_url = base_url.rstrip("/")

    def name(self) -> str:
        return "mcp_call"

    def run(self, arguments: Dict[str, Any]) -> Any:
        """Execute a tool call via orchestrator HTTP API."""
        tool_name = arguments.get("tool")
        if not tool_name:
            return {"status": "error", "error": "Missing required parameter 'tool'"}

        try:
            response = requests.post(
                f"{self.base_url}/tool",
                json={"tool": tool_name, "arguments": arguments.get("arguments", {})},
                timeout=30.0
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"status": "error", "error": f"Tool '{tool_name}' failed: {e}"}
