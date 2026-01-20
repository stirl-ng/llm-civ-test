from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict


class Tool(ABC):
    @abstractmethod
    def name(self) -> str:  # pragma: no cover - trivial
        ...

    @abstractmethod
    def run(self, arguments: Dict[str, Any]) -> Any:
        ...


class RequestToolTool(Tool):
    """Stub tool for capturing LLM tool requests/hallucinations."""

    def __init__(self, log_path: str = "tool_requests.jsonl"):
        self.log_path = log_path

    def name(self) -> str:
        return "request_tool"

    def run(self, arguments: Dict[str, Any]) -> Any:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "tool_name": arguments.get("tool_name", "unknown"),
            "description": arguments.get("description", ""),
            "parameters": arguments.get("parameters", {}),
            "use_case": arguments.get("use_case", ""),
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return {"status": "logged", "message": f"Tool request '{entry['tool_name']}' logged for future implementation."}

