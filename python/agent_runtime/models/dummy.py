from __future__ import annotations

from typing import Any, Dict, List, Optional

from .base import ModelAdapter, GenerateResponse


class DummyModel(ModelAdapter):
    """
    Deterministic, offline model for tests and dry runs.
    Returns a canned response; no network needed.
    """

    def __init__(self, seed: int = 0, name: str = "dummy") -> None:
        self._name = f"{name}:{seed}"

    def name(self) -> str:  # pragma: no cover - trivial
        return self._name

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> GenerateResponse:
        # Echo last user line for traceability
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        return GenerateResponse(
            text=f"ACK: {last_user[:120]}",
            tool_calls=[],
            usage={},
        )
