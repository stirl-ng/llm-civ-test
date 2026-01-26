from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from .base import ModelAdapter, GenerateResponse, ToolCall

# Try to import message logger
_message_logger = None
try:
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    pass


class GeminiChat(ModelAdapter):
    """Google Gemini chat model adapter with native function calling support."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            raise ImportError("google-genai package required: pip install google-genai") from e

        self._genai = genai
        self._types = types
        self._model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
        api_key = api_key or os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("GEMINI_API_KEY required (env var or config)")

        self._client = genai.Client(api_key=api_key)

    def name(self) -> str:
        return f"gemini:{self._model_name}"

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any
    ) -> GenerateResponse:
        """Generate response with optional native function calling.

        Args:
            messages: Chat messages in OpenAI format. For tool results, use:
                {"role": "tool", "tool_call_id": "...", "name": "...", "content": "..."}
            tools: Optional tool definitions in OpenAI format (will be converted)
            **kwargs: temperature, etc.

        Returns:
            GenerateResponse with text and/or tool_calls
        """
        temperature = kwargs.get("temperature", 0.2)

        # Convert messages to Gemini format
        contents, system_instruction = self._convert_messages(messages)

        # Log request
        request_uuid = None
        if _message_logger:
            try:
                request_uuid = _message_logger.log_llm_request(
                    model=self._model_name,
                    messages=messages,
                    temperature=temperature,
                    tools=[t["function"]["name"] for t in tools] if tools else None,
                )
            except Exception:
                pass

        # Build config
        config: Dict[str, Any] = {"temperature": temperature}
        if system_instruction:
            config["system_instruction"] = system_instruction

        # Convert and add tools if provided
        gemini_tools = None
        if tools:
            gemini_tools = self._convert_tools(tools)

        # Make API call
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=self._types.GenerateContentConfig(
                temperature=temperature,
                system_instruction=system_instruction,
                tools=gemini_tools,
            ),
        )

        # Extract text content
        text = ""
        tool_calls: List[ToolCall] = []

        # Process response parts
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "text") and part.text:
                    text += part.text
                elif hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    # Gemini doesn't provide IDs, so we generate our own
                    tool_calls.append(ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))

        text = text.strip()

        # Extract token usage
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", None),
                "completion_tokens": getattr(um, "candidates_token_count", None),
                "total_tokens": getattr(um, "total_token_count", None),
            }

        # Log response
        if _message_logger and request_uuid:
            try:
                _message_logger.log_llm_response(
                    request_uuid=request_uuid,
                    response=text,
                    tool_calls=[{"name": tc.name, "arguments": tc.arguments} for tc in tool_calls],
                    **{k: v for k, v in usage.items() if v is not None},
                )
            except Exception:
                pass

        return GenerateResponse(
            text=text,
            tool_calls=tool_calls,
            raw_response=response,
            usage=usage,
        )

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[List[Any], Optional[str]]:
        """Convert OpenAI-format messages to Gemini format.

        Returns:
            Tuple of (contents list, system instruction string or None)
        """
        contents = []
        system_parts = []

        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
                i += 1
                continue

            if role == "user":
                contents.append(self._types.Content(
                    role="user",
                    parts=[self._types.Part.from_text(content)],
                ))
                i += 1

            elif role == "assistant":
                parts = []
                # Add text if present
                if content:
                    parts.append(self._types.Part.from_text(content))

                # Add function calls if present
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        parts.append(self._types.Part.from_function_call(
                            name=tc["function"]["name"],
                            args=json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                        ))

                if parts:
                    contents.append(self._types.Content(role="model", parts=parts))
                i += 1

            elif role == "tool":
                # Collect consecutive tool results
                tool_results = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    result_content = tool_msg.get("content", "")
                    # Try to parse as JSON, otherwise use as string
                    try:
                        result_data = json.loads(result_content)
                    except (json.JSONDecodeError, TypeError):
                        result_data = {"result": result_content}

                    tool_results.append(self._types.Part.from_function_response(
                        name=tool_msg.get("name", "unknown"),
                        response=result_data,
                    ))
                    i += 1

                if tool_results:
                    contents.append(self._types.Content(role="user", parts=tool_results))

            else:
                # Unknown role, treat as user
                contents.append(self._types.Content(
                    role="user",
                    parts=[self._types.Part.from_text(content)],
                ))
                i += 1

        # Combine system parts
        system_instruction = "\n\n".join(system_parts) if system_parts else None

        return contents, system_instruction

    def _convert_tools(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """Convert OpenAI-format tools to Gemini function declarations."""
        declarations = []
        for tool in tools:
            func = tool.get("function", {})
            declarations.append(self._types.FunctionDeclaration(
                name=func.get("name", ""),
                description=func.get("description", ""),
                parameters=func.get("parameters", {}),
            ))
        return [self._types.Tool(function_declarations=declarations)]
