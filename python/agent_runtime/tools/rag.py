"""RAG tool stub - placeholder for future XML/game data retrieval."""

from typing import Any, Dict

from .base import Tool


class LocalRAG(Tool):
    """Placeholder for future RAG over Civ V game data (XML files, etc.)."""

    def __init__(self, **kwargs: Any):
        pass  # Accept any kwargs for forward compatibility

    def name(self) -> str:
        return "rag_search"

    def run(self, arguments: Dict[str, Any]) -> Any:
        return {"status": "not_implemented", "message": "RAG not yet implemented"}
