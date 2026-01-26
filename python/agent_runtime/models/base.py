from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolCall:
    """Represents a single tool call from the model."""
    id: str  # Unique ID for this tool call (used for multi-turn conversations)
    name: str  # Tool name
    arguments: Dict[str, Any]  # Tool arguments


@dataclass
class GenerateResponse:
    """Structured response from model generation with tool support.

    Attributes:
        text: The text content of the response (may be empty if only tool calls)
        tool_calls: List of tool calls requested by the model
        raw_response: The raw response object from the provider (for debugging)
        usage: Token usage information if available
    """
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_response: Any = None
    usage: Dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class ToolResult:
    """Result of executing a tool, to be passed back to the model."""
    tool_call_id: str  # ID of the tool call this is responding to
    name: str  # Tool name (for display/logging)
    result: Any  # The result (will be JSON serialized)
    is_error: bool = False


class ModelAdapter(ABC):
    """Abstract interface for model backends supporting native tool calling."""

    @abstractmethod
    def name(self) -> str:  # pragma: no cover - trivial
        """Return a human-readable name for this model."""
        ...

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> GenerateResponse:
        """Generate a response, optionally with tool calling support.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
                      For tool results, include 'tool_call_id' and 'name'.
            tools: Optional list of tool definitions in OpenAI format.
                   If provided, model may return tool_calls in response.
            **kwargs: Additional provider-specific options (temperature, etc.)

        Returns:
            GenerateResponse with text and/or tool_calls
        """
        ...

    def generate_text(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """Convenience method: generate without tools, return just text.

        This is for backwards compatibility and simple use cases.
        """
        response = self.generate(messages, tools=None, **kwargs)
        return response.text
