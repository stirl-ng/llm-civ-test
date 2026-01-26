"""Tool schemas for native LLM tool calling.

Defines OpenAI-compatible tool schemas that can be converted to other formats
(Gemini function_declarations, Anthropic tools, etc.) as needed.
"""

from typing import Any

# OpenAI-compatible tool definitions
# These map directly to the orchestrator's /tool endpoint
TOOL_SCHEMAS: list[dict[str, Any]] = [
    # === Query Tools ===
    {
        "type": "function",
        "function": {
            "name": "get_units",
            "description": "Get all units owned by the player with their IDs, positions, types, and moves remaining.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cities",
            "description": "Get all cities owned by the player with IDs, population, and current production.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "Optional: Get info for a specific city only",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_city_production",
            "description": "Get available production options (units, buildings, wonders, processes) for a specific city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "ID of the city to query",
                    },
                },
                "required": ["city_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_techs",
            "description": "Get technologies available for research.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_policies",
            "description": "Get policy branches and policies available for adoption.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_turn_blockers",
            "description": "Get all current end-turn blockers (units needing orders, required choices, etc.).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_notifications",
            "description": "Get recent game notifications and events.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_game_state",
            "description": "Get general game state information.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    # === Spatial Awareness Tools ===
    {
        "type": "function",
        "function": {
            "name": "get_map_view",
            "description": "ESSENTIAL: Get ASCII map showing terrain, units, cities, resources around a location. Use frequently to understand the world before moving units or making decisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "center": {
                        "type": "string",
                        "description": "Center point: 'capital', 'unit:<id>', or '<x>,<y>'. Default: 'capital'",
                    },
                    "radius": {
                        "type": "integer",
                        "description": "Tiles from center to edge. Default: 10",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_reachable_tiles",
            "description": "Get all tiles a unit can move to THIS turn, including attackable enemies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "integer",
                        "description": "ID of the unit to check movement for",
                    },
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_unit_build_options",
            "description": "Get what a Worker can build (farms, mines, roads, etc.) on nearby tiles.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "integer",
                        "description": "ID of the worker/builder unit",
                    },
                    "radius": {
                        "type": "integer",
                        "description": "Search radius from unit. Default: 5",
                    },
                },
                "required": ["unit_id"],
            },
        },
    },
    # === Memory Tools ===
    {
        "type": "function",
        "function": {
            "name": "query_knowledge_base",
            "description": "Read stored knowledge from persistent memory. Use to recall strategy, diplomatic relations, lessons learned.",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {
                        "type": "string",
                        "description": "Section to read (e.g., 'strategy', 'plan'). Omit or null for all sections.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_knowledge_base",
            "description": "Update persistent memory. Store strategy, diplomatic history, important decisions, lessons learned, multi-turn plans.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["set", "delete"],
                        "description": "'set' to create/update, 'delete' to remove section",
                    },
                    "section_id": {
                        "type": "string",
                        "description": "Section name (e.g., 'strategy', 'plan', 'gandhi', 'lessons')",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to store (required for 'set' operation)",
                    },
                },
                "required": ["operation", "section_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_log",
            "description": "Query conversation history and game events. Use to review previous decisions and learn from what worked.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_type": {
                        "type": "string",
                        "description": "Filter by type (e.g., 'llm_response', 'tool_response', 'notification')",
                    },
                    "turn_number": {
                        "type": "integer",
                        "description": "Filter by specific turn",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max entries to return. Default: 100",
                    },
                },
                "required": [],
            },
        },
    },
    # === Action Tools ===
    {
        "type": "function",
        "function": {
            "name": "send_action",
            "description": "Send a unit action command. Use for move_unit, unit_found_city, unit_alert, unit_sleep, unit_skip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "object",
                        "description": "Action object with 'kind' and parameters. Examples: {\"kind\": \"move_unit\", \"unit_id\": 123, \"to\": [10, 15]}, {\"kind\": \"unit_alert\", \"unit_id\": 123}, {\"kind\": \"unit_found_city\", \"unit_id\": 123}",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["move_unit", "unit_found_city", "unit_alert", "unit_sleep", "unit_skip"],
                                "description": "Action type",
                            },
                            "unit_id": {
                                "type": "integer",
                                "description": "ID of the unit to command",
                            },
                            "to": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Target coordinates [x, y] for move_unit",
                            },
                        },
                        "required": ["kind", "unit_id"],
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_city_production",
            "description": "Set what a city should produce.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "ID of the city",
                    },
                    "order_type": {
                        "type": "integer",
                        "enum": [0, 1, 2, 3],
                        "description": "0=unit, 1=building, 2=wonder, 3=process",
                    },
                    "item_id": {
                        "type": "integer",
                        "description": "ID of the unit/building/wonder/process to produce",
                    },
                },
                "required": ["city_id", "order_type", "item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "choose_tech",
            "description": "Select a technology to research.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tech_id": {
                        "type": "integer",
                        "description": "ID of the technology to research",
                    },
                },
                "required": ["tech_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adopt_policy",
            "description": "Adopt a policy or unlock a policy branch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "policy_id": {
                        "type": "integer",
                        "description": "ID of policy to adopt (use this OR branch_id)",
                    },
                    "branch_id": {
                        "type": "integer",
                        "description": "ID of branch to unlock (use this OR policy_id)",
                    },
                },
                "required": [],
            },
        },
    },
    # === Turn Control ===
    {
        "type": "function",
        "function": {
            "name": "end_turn",
            "description": "End your turn. Will fail if there are unresolved blockers (units needing orders, required choices). Use get_turn_blockers to check first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "turn": {
                        "type": "integer",
                        "description": "Current turn number (for validation)",
                    },
                },
                "required": ["turn"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "force_end_turn",
            "description": "Force end turn, bypassing some checks like blocking units. Use when end_turn fails and you cannot resolve blockers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "turn": {
                        "type": "integer",
                        "description": "Current turn number (for validation)",
                    },
                },
                "required": ["turn"],
            },
        },
    },
    # === Popup Choices ===
    {
        "type": "function",
        "function": {
            "name": "select_pantheon",
            "description": "Select a pantheon belief when prompted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "belief_id": {
                        "type": "integer",
                        "description": "ID of the belief to select",
                    },
                },
                "required": ["belief_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "found_religion",
            "description": "Found a new religion when prompted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "religion_id": {
                        "type": "integer",
                        "description": "ID of the religion to found",
                    },
                    "founder_belief_id": {
                        "type": "integer",
                        "description": "ID of the founder belief",
                    },
                    "follower_belief_id": {
                        "type": "integer",
                        "description": "ID of the follower belief",
                    },
                },
                "required": ["religion_id", "founder_belief_id", "follower_belief_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enhance_religion",
            "description": "Enhance an existing religion when prompted.",
            "parameters": {
                "type": "object",
                "properties": {
                    "follower2_belief_id": {
                        "type": "integer",
                        "description": "ID of the second follower belief",
                    },
                    "enhancer_belief_id": {
                        "type": "integer",
                        "description": "ID of the enhancer belief",
                    },
                },
                "required": ["follower2_belief_id", "enhancer_belief_id"],
            },
        },
    },
    # === Utility ===
    {
        "type": "function",
        "function": {
            "name": "request_tool",
            "description": "Log a request for a tool that doesn't exist yet. Use when you need functionality that no tool provides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Suggested name for the tool",
                    },
                    "description": {
                        "type": "string",
                        "description": "What the tool should do",
                    },
                    "use_case": {
                        "type": "string",
                        "description": "Why you need this tool",
                    },
                },
                "required": ["tool_name", "description"],
            },
        },
    },
]


def get_openai_tools() -> list[dict[str, Any]]:
    """Get tool schemas in OpenAI format."""
    return TOOL_SCHEMAS


def get_gemini_tools() -> list[dict[str, Any]]:
    """Convert tool schemas to Gemini function_declarations format."""
    declarations = []
    for tool in TOOL_SCHEMAS:
        func = tool["function"]
        declarations.append({
            "name": func["name"],
            "description": func["description"],
            "parameters": func["parameters"],
        })
    return declarations


def get_tool_names() -> list[str]:
    """Get list of all tool names."""
    return [tool["function"]["name"] for tool in TOOL_SCHEMAS]
