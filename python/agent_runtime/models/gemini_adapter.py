from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .base import ModelAdapter

# Try to import message logger
_message_logger = None
try:
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    pass


class GeminiChat(ModelAdapter):
    """Google Gemini chat model adapter using google.genai SDK."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        try:
            from google import genai
        except ImportError as e:
            raise ImportError("google-genai package required: pip install google-genai") from e

        self._model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
        api_key = api_key or os.environ.get("GEMINI_API_KEY")

        if not api_key:
            raise ValueError("GEMINI_API_KEY required (env var or config)")

        self._client = genai.Client(api_key=api_key)

    def name(self) -> str:
        return f"gemini:{self._model_name}"

    def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """Generate response. Converts OpenAI message format to Gemini format."""
        temperature = kwargs.get("temperature", 0.2)

        # Convert messages to Gemini format
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
            elif role == "user":
                # Prepend system to first user message
                if system_parts and not contents:
                    content = "\n\n".join(system_parts + [content])
                    system_parts = []
                contents.append({"role": "user", "parts": [{"text": content}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})

        if not contents:
            return ""

        # Log request
        request_uuid = None
        if _message_logger:
            try:
                request_uuid = _message_logger.log_llm_request(
                    model=self._model_name,
                    messages=messages,
                    temperature=temperature,
                )
            except Exception:
                pass

        # Generate
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config={"temperature": temperature}
        )

        response_text = (response.text or "").strip()

        # Extract token usage (Gemini uses usage_metadata)
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", None),
                "completion_tokens": getattr(um, "candidates_token_count", None),
                "total_tokens": getattr(um, "total_token_count", None),
            }

        # Log response with token usage
        if _message_logger and request_uuid:
            try:
                _message_logger.log_llm_response(request_uuid=request_uuid, response=response_text, **usage)
            except Exception:
                pass

        return response_text
