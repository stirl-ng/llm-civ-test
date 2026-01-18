from __future__ import annotations

from typing import Any, Dict, List, Optional

from .mcp import MCPClientTool


def build_tools(configs: List[Dict[str, Any]] | None, base_url: Optional[str] = None) -> List[Any]:
    """Build tools from configuration.

    Args:
        configs: List of tool configuration dicts
        base_url: Base URL for orchestrator (used for MCP tools if not in config)

    Returns:
        List of tool instances
    """
    tools: List[Any] = []
    for cfg in configs or []:
        kind = (cfg.get("kind") or cfg.get("type") or "").lower()
        if kind == "mcp":
            mcp_base_url = cfg.get("base_url") or base_url or "http://localhost:8765"
            tools.append(MCPClientTool(base_url=mcp_base_url))
        else:
            raise ValueError(f"Unsupported tool kind: {kind}")
    return tools

