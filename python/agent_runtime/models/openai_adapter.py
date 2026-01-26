from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .base import ModelAdapter, GenerateResponse, ToolCall

# Try to import message logger (may not be available if orchestrator not running)
_message_logger = None
try:
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    pass


class OpenAIChat(ModelAdapter):
    """
    OpenAI-compatible chat model adapter with native tool calling support.

    Supports OpenAI and compatible servers via base_url (Azure, vLLM, Ollama, etc.)

    Config keys (via constructor or env):
    - model: required (env OPENAI_MODEL)
    - api_key: optional if server doesn't require (env OPENAI_API_KEY)
    - base_url: override API host (env OPENAI_BASE_URL)
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, base_url: Optional[str] = None):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover - import time
            raise ImportError("openai package is required for OpenAIChat") from e

        self._OpenAI = OpenAI
        self._model = model or os.environ.get("OPENAI_MODEL")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        if not self._model:
            raise ValueError("model is required (set in config or OPENAI_MODEL)")

        # Initialize client; OpenAI SDK accepts base_url for compat servers
        kwargs: Dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = self._OpenAI(**kwargs)

    def name(self) -> str:  # pragma: no cover - trivial
        host = self._base_url or "openai"
        return f"openai:{self._model}@{host}"

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> GenerateResponse:
        """Generate response with optional native tool calling.

        Args:
            messages: Chat messages. For tool results, use format:
                {"role": "tool", "tool_call_id": "...", "content": "..."}
            tools: Optional tool definitions in OpenAI format
            **kwargs: temperature, etc.

        Returns:
            GenerateResponse with text and/or tool_calls
        """
        temperature = kwargs.get("temperature", 0.2)

        # Log LLM request
        request_uuid = None
        if _message_logger:
            try:
                request_uuid = _message_logger.log_llm_request(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    tools=[t["function"]["name"] for t in tools] if tools else None,
                )
            except Exception:
                pass  # Don't fail if logging fails

        # Build API call kwargs
        api_kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": self._convert_messages(messages),
            "temperature": temperature,
        }

        # Add tools if provided
        if tools:
            api_kwargs["tools"] = tools
            # Allow model to choose whether to call tools or respond with text
            api_kwargs["tool_choice"] = "auto"

        # Make API call
        res = self._client.chat.completions.create(**api_kwargs)
        msg = res.choices[0].message

        # Extract text content
        text = (msg.content or "").strip()

        # Extract tool calls
        tool_calls: List[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        # Extract token usage
        usage = {}
        if res.usage:
            usage = {
                "prompt_tokens": res.usage.prompt_tokens,
                "completion_tokens": res.usage.completion_tokens,
                "total_tokens": res.usage.total_tokens,
            }

        # Log LLM response with token usage
        if _message_logger and request_uuid:
            try:
                _message_logger.log_llm_response(
                    request_uuid=request_uuid,
                    response=text,
                    tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
                    **usage,
                )
            except Exception:
                pass  # Don't fail if logging fails

        return GenerateResponse(
            text=text,
            tool_calls=tool_calls,
            raw_response=res,
            usage=usage,
        )

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert messages to OpenAI format, handling tool results."""
        converted = []
        for msg in messages:
            role = msg.get("role", "user")

            # Handle tool results
            if role == "tool":
                converted.append({
                    "role": "tool",
                    "tool_call_id": msg.get("tool_call_id", ""),
                    "content": msg.get("content", ""),
                })
            # Handle assistant messages that may contain tool calls
            elif role == "assistant" and msg.get("tool_calls"):
                converted.append({
                    "role": "assistant",
                    "content": msg.get("content"),
                    "tool_calls": msg["tool_calls"],
                })
            else:
                converted.append({
                    "role": role,
                    "content": msg.get("content", ""),
                })

        return converted
