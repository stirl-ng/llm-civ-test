"""Model adapters for LLM backends."""

from .registry import get_model

__all__ = ["get_model"]
