# Plan: Schema Sync Enforcement

## Problem

Two parallel tool definitions exist and must be kept in sync manually:

1. `python/orchestrator/mcp_server.py` — `_TOOLS` dict inside `CivMCPServer`. What the orchestrator handles.
2. `python/agent_runtime/tools/schemas.py` — `TOOL_SCHEMAS` list in OpenAI format. What the LLM sees.

No test, no check, no enforcement. They can drift silently.

---

## Analysis

Tools fall into three categories:

| Category | In `_TOOLS`? | In `TOOL_SCHEMAS`? | Handled by |
|---|---|---|---|
| Orchestrator tools | Yes | Yes | `mcp_server` → DLL |
| Local tools | No | Yes | `run.py` directly (journal) |
| Internal tools | Yes | No | Orchestrator only, LLM never calls |

**Internal tools** (intentionally hidden from LLM): `get_tools`, `ping`

**Local tools** (handled in `run.py`, not orchestrator): `record_recap`, `record_lesson`,
`get_lessons`, `get_recaps`, `update_strategy`, `request_tool`

**`_PLACEHOLDER_TOOLS`**: `get_tech_tree`, `get_diplomacy`, `get_available_choices`,
`get_victory_progress`, `get_resources`, `get_player_status` — not in schemas (correct, unimplemented)

### Real drift bugs found

| Tool | In `_TOOLS`? | In `TOOL_SCHEMAS`? | Problem |
|---|---|---|---|
| `get_current_turn` | Yes | **No** | LLM cannot call it |
| `get_log` | Yes | **No** | LLM cannot call it |

---

## Chosen Approach: Option C — Test enforcement

Option A/B (auto-generate one from the other) is blocked by format mismatch: `_TOOLS` uses
informal English param strings; `TOOL_SCHEMAS` has proper JSON Schema with types/enums/nested
objects. Merging would be a large refactor.

Option D (dataclass consolidation) is the right long-term answer but too disruptive now.

Option C: keep both, add a test that fails if they diverge. ~40 lines, catches drift
immediately, no restructuring. Do this now. Revisit Option D when adding a batch of new tools.

---

## Files to Change

| File | Change |
|---|---|
| `python/agent_runtime/tools/schemas.py` | Add missing entries for `get_current_turn` and `get_log` |
| `python/tests/test_schema_sync.py` | **New** — 4 tests enforcing sync |

(`python/tests/__init__.py` and `conftest.py` already exist or are minimal; check first.)

---

## Step 1 — Fix the two drift bugs in `schemas.py`

Add to `TOOL_SCHEMAS`:

```python
{
    "type": "function",
    "function": {
        "name": "get_current_turn",
        "description": "Returns the current turn number.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "get_log",
        "description": "Returns recent game log entries.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of entries to return.",
                    "default": 20
                }
            },
            "required": []
        }
    }
},
```

> Verify the actual parameter signature of `get_log` in `mcp_server.py` before finalising.

---

## Step 2 — `python/tests/test_schema_sync.py` (new file)

```python
"""
Ensures mcp_server._TOOLS and tools/schemas.py stay in sync.

Rules:
- Every orchestrator tool must have a schema entry (so LLM can call it).
- Every schema entry must have a handler (orchestrator or local in run.py).
- Internal tools must NOT be in schemas.
- Placeholder tools must NOT be in schemas until implemented.

When adding a new tool, update one of the sets below if needed.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.mcp_server import CivMCPServer
from agent_runtime.tools.schemas import get_tool_names

# Tools intentionally excluded from LLM-visible schemas
INTERNAL_TOOLS = {"get_tools", "ping"}

# Tools handled locally in run.py (not routed through orchestrator)
LOCAL_TOOLS = {
    "record_recap", "record_lesson", "get_lessons",
    "get_recaps", "update_strategy", "request_tool",
}


def _get_orchestrator_tool_names() -> set[str]:
    # Instantiate with dummy callbacks to access _TOOLS
    server = CivMCPServer(send_request=lambda r, **kw: {}, game_state=None)
    return set(server._TOOLS.keys()) - INTERNAL_TOOLS


def _get_schema_tool_names() -> set[str]:
    return set(get_tool_names())


def test_orchestrator_tools_have_schemas():
    """Every non-internal orchestrator tool must be visible to the LLM."""
    orch = _get_orchestrator_tool_names()
    schema = _get_schema_tool_names()
    missing = orch - schema - INTERNAL_TOOLS
    assert not missing, (
        f"Tools in _TOOLS but missing from TOOL_SCHEMAS (LLM can't call them):\n"
        + "\n".join(f"  - {t}" for t in sorted(missing))
    )


def test_schema_tools_have_handlers():
    """Every schema tool must have a handler (orchestrator or local)."""
    orch = _get_orchestrator_tool_names()
    schema = _get_schema_tool_names()
    all_handled = orch | LOCAL_TOOLS
    unhandled = schema - all_handled
    assert not unhandled, (
        f"Tools in TOOL_SCHEMAS with no handler in _TOOLS or LOCAL_TOOLS:\n"
        + "\n".join(f"  - {t}" for t in sorted(unhandled))
    )


def test_internal_tools_not_in_schemas():
    """Internal tools must stay hidden from the LLM."""
    schema = _get_schema_tool_names()
    leaked = INTERNAL_TOOLS & schema
    assert not leaked, f"Internal tools leaked into TOOL_SCHEMAS: {leaked}"


def test_placeholder_tools_not_in_schemas():
    """Placeholder (unimplemented) tools must not be in schemas."""
    server = CivMCPServer(send_request=lambda r, **kw: {}, game_state=None)
    placeholders = set(server._PLACEHOLDER_TOOLS.keys())
    schema = _get_schema_tool_names()
    premature = placeholders & schema
    assert not premature, (
        f"Placeholder tools in TOOL_SCHEMAS before implementation: {premature}"
    )
```

---

## Verification

```bash
cd python
pytest tests/test_schema_sync.py -v
```

All 4 tests should pass after the `schemas.py` fix. On subsequent tool additions, the tests fail
immediately if either file is updated without the other.

---

## Notes

- `CivMCPServer` must be instantiable with dummy args for the test to work. Verify this doesn't
  trigger side effects (file I/O, network) — if it does, mock the constructor or extract `_TOOLS`
  as a class-level dict.
- Long-term (Option D): define tools as dataclasses with both handler reference + schema inline.
  Do this when adding the next batch of 5+ tools, not as a standalone refactor.
