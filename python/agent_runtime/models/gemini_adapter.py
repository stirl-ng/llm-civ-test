from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .base import ModelAdapter

# Try to import message logger (may not be available if orchestrator not running)
_message_logger = None
try:
    # Import from orchestrator package (requires python/ to be in PYTHONPATH)
    from orchestrator.message_logger import get_message_logger
    _message_logger = get_message_logger()
except ImportError:
    pass  # Logger not available, logging will be skipped


class GeminiChat(ModelAdapter):
    """
    Google Gemini chat model adapter using the new google.genai SDK.

    Config keys (via constructor or env):
    - model: required (env GEMINI_MODEL, defaults to "gemini-2.0-flash-exp")
    - api_key: required (env GEMINI_API_KEY)
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        try:
            from google import genai  # type: ignore
        except Exception as e:  # pragma: no cover - import time
            raise ImportError(
                "google-genai package is required for GeminiChat. "
                "Install with: pip install google-genai"
            ) from e

        self._genai = genai
        self._model_name = model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-exp")
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")

        if not self._api_key:
            raise ValueError(
                "Gemini API key is required. "
                "Set it in config (backend.api_key) or environment variable (GEMINI_API_KEY). "
                "Get your API key from: https://aistudio.google.com/app/apikey"
            )

        # Initialize the client with API key
        try:
            self._client = self._genai.Client(api_key=self._api_key)
        except Exception as e:
            raise ValueError(f"Failed to initialize Gemini client: {e}") from e

        # Validate model exists by trying to list models
        try:
            self._validate_model()
        except Exception as e:
            # If validation fails, try to list available models
            error_msg = str(e)
            error_type = type(e).__name__

            is_not_found = (
                "NotFound" in error_type
                or "not found" in error_msg.lower()
                or "404" in error_msg
                or "is not found" in error_msg.lower()
            )

            if is_not_found:
                try:
                    available_models = self._list_available_models()
                    available_list = "\n  ".join(sorted(available_models))
                    raise ValueError(
                        f"Model '{self._model_name}' not found.\n\n"
                        f"Available models:\n  {available_list}\n\n"
                        f"Set the model name in config (backend.model) or GEMINI_MODEL env var."
                    ) from e
                except Exception as list_error:
                    raise ValueError(
                        f"Model '{self._model_name}' not found. "
                        f"Failed to list available models: {list_error}"
                    ) from e
            raise

    def _validate_model(self) -> None:
        """Validate that the model exists by listing models."""
        models = self._list_available_models()
        if self._model_name not in models:
            raise ValueError(
                f"Model '{self._model_name}' not in available models:\n  {'\n'.join(models)}"
            )

    def _list_available_models(self) -> List[str]:
        """List available models from the API."""
        available_models = []
        try:
            for model in self._client.models.list():
                model_name = model.name.replace('models/', '')
                available_models.append(model_name)
        except Exception as e:
            # If listing fails, try a test generation to see what error we get
            raise ValueError(f"Failed to list models: {e}") from e
        return available_models

    def name(self) -> str:  # pragma: no cover - trivial
        return f"gemini:{self._model_name}"

    def generate(self, messages: List[Dict[str, str]], **kwargs: Any) -> str:
        """
        Generate a response from Gemini given a chat message list.

        Converts OpenAI-style message format to Gemini's format.
        System messages are prepended to the first user message.
        """
        temperature = kwargs.get("temperature", 0.2)

        # Build contents list from messages
        # New API uses a list of content parts
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                system_parts.append(content)
            elif role == "user":
                # Combine system parts with user message if this is the first user message
                if system_parts and not contents:
                    full_content = "\n\n".join(system_parts + [content])
                    system_parts = []  # Clear after using
                else:
                    full_content = content
                contents.append({"role": "user", "parts": [{"text": full_content}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})

        # If we have system parts but no user messages, prepend to first content
        if system_parts and contents:
            first_content = contents[0]
            if first_content.get("role") == "user":
                first_parts = first_content.get("parts", [])
                if first_parts and "text" in first_parts[0]:
                    first_parts[0]["text"] = "\n\n".join(system_parts + [first_parts[0]["text"]])

        # If no contents, return empty
        if not contents:
            return ""

        # Log LLM request
        request_uuid = None
        if _message_logger:
            try:
                # Convert contents back to messages format for logging
                log_messages = []
                for content in contents:
                    role = "user" if content.get("role") == "user" else "assistant"
                    parts = content.get("parts", [])
                    text = " ".join(p.get("text", "") for p in parts if "text" in p)
                    log_messages.append({"role": role, "content": text})
                request_uuid = _message_logger.log_llm_request(
                    model=self._model_name,
                    messages=log_messages,
                    temperature=temperature,
                )
            except Exception:
                pass  # Don't fail if logging fails

        # Generate response using new API
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=contents,
                config={"temperature": temperature}
            )

            # Check for finish reasons that indicate problems
            if response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)

                if finish_reason:
                    finish_reason_str = str(finish_reason)
                    # Check for MALFORMED_FUNCTION_CALL - this happens when Gemini tries to use
                    # native function calling but no functions are registered
                    if "MALFORMED_FUNCTION_CALL" in finish_reason_str:
                        raise ValueError(
                            "Gemini API returned MALFORMED_FUNCTION_CALL. "
                            "This typically occurs when the model tries to use native function calling "
                            "but no functions are registered with the API. "
                            "The system prompt should instruct the model to output function calls as TEXT, "
                            "not use native function calling. Check that the prompt explicitly states: "
                            "'Output function calls as plain text, not as native function calls.'"
                        )
                    elif "SAFETY" in finish_reason_str:
                        raise ValueError(
                            "Gemini API blocked the response due to safety filters. "
                            f"Finish reason: {finish_reason_str}"
                        )
                    elif "RECITATION" in finish_reason_str:
                        raise ValueError(
                            "Gemini API blocked the response due to recitation policy. "
                            f"Finish reason: {finish_reason_str}"
                        )

            # Get response text, handling None case
            response_text = (response.text or "").strip()

            # If response is empty and we have a problematic finish reason, provide better error
            if not response_text and response.candidates:
                candidate = response.candidates[0]
                finish_reason = getattr(candidate, 'finish_reason', None)
                if finish_reason:
                    finish_reason_str = str(finish_reason)
                    if "MALFORMED_FUNCTION_CALL" in finish_reason_str:
                        raise ValueError(
                            "Gemini API returned empty response with MALFORMED_FUNCTION_CALL. "
                            "The model tried to use native function calling but no functions are registered. "
                            "Ensure the system prompt instructs the model to output function calls as TEXT only."
                        )

            # Log LLM response
            if _message_logger and request_uuid:
                try:
                    _message_logger.log_llm_response(
                        request_uuid=request_uuid,
                        response=response_text,
                    )
                except Exception:
                    pass  # Don't fail if logging fails

            return response_text
        except Exception as e:
            # If model not found during generation, list available models
            error_msg = str(e)
            error_type = type(e).__name__

            is_not_found = (
                "NotFound" in error_type
                or "not found" in error_msg.lower()
                or "404" in error_msg
                or "is not found" in error_msg.lower()
            )

            if is_not_found:
                try:
                    available_models = self._list_available_models()
                    available_list = "\n  ".join(sorted(available_models))
                    raise ValueError(
                        f"Model '{self._model_name}' not found during generation.\n\n"
                        f"Available models:\n  {available_list}\n\n"
                        f"Set the model name in config (backend.model) or GEMINI_MODEL env var."
                    ) from e
                except Exception as list_error:
                    raise ValueError(
                        f"Model '{self._model_name}' not found during generation. "
                        f"Failed to list available models: {list_error}"
                    ) from e
            raise
