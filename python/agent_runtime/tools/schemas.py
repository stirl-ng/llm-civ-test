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
            "description": "Get available production options (units, buildings, wonders, processes) for a specific city. Returns item IDs needed for set_city_production.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "ID of the city. Must come from get_cities results — never guess.",
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
    {
        "type": "function",
        "function": {
            "name": "get_current_turn",
            "description": "Returns the current turn number.",
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
            "name": "get_log",
            "description": "Returns recent game log entries with optional filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_type": {
                        "type": "string",
                        "description": "Filter by message type (e.g. 'turn_start', 'notification')",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["incoming", "outgoing"],
                        "description": "Filter by message direction",
                    },
                    "turn_number": {
                        "type": "integer",
                        "description": "Filter by turn number",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of entries to return. Default: 100, max: 1000",
                    },
                    "current_game_only": {
                        "type": "boolean",
                        "description": "Only return entries from the current game. Default: true",
                    },
                },
                "required": [],
            },
        },
    },
    # === Spatial Awareness Tools ===
    {
        "type": "function",
        "function": {
            "name": "get_visible_tiles",
            "description": "Get raw tile data for all revealed tiles. Prefer get_map_view for visual overview.",
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
            "name": "get_map_view",
            "description": "ESSENTIAL: Get ASCII map + structured tile data around a location. Returns 'map' (ASCII with legend) and 'tiles' (array of objects with x, y, terrain, feature, resource, improvement, route, territory_owner, units, city per tile). Use frequently before moving units or making decisions.",
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
                        "description": "ID of the unit. Must come from get_units results — never guess.",
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
                        "description": "ID of the worker/builder unit. Must come from get_units results — never guess.",
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
            "name": "record_recap",
            "description": "Record your recap of this turn. Write 2-4 sentences: what happened, what you're planning, how things are going. Called automatically during reflection, but you can call it anytime.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Your turn recap (2-4 sentences on what happened and what you're planning)",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_strategy",
            "description": "Update your current high-level strategy. This persists across turns and appears in your briefing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "strategy": {
                        "type": "string",
                        "description": "Your current high-level strategy",
                    },
                },
                "required": ["strategy"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recaps",
            "description": "Get your most recent turn recaps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max recaps to return. Default: 3",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_lesson",
            "description": "Record a lesson learned that will persist across games. Use when you learn something generally applicable (not game-specific). Your future self will see these lessons at the start of new games.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lesson": {
                        "type": "string",
                        "description": "The lesson learned (e.g., 'Early aggression from AI often escalates to war', 'Coastal cities need naval defense')",
                    },
                    "category": {
                        "type": "string",
                        "enum": ["diplomacy", "military", "economy", "expansion", "research", "general"],
                        "description": "Category of lesson",
                    },
                },
                "required": ["lesson"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_lessons",
            "description": "Retrieve lessons you've learned from previous games. These are your accumulated wisdom as a player.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["diplomacy", "military", "economy", "expansion", "research", "general"],
                        "description": "Filter by category (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max lessons to return. Default: 10",
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
            "description": "Send a unit action command. Use for move_unit, unit_found_city, unit_alert, unit_sleep, unit_skip. Always call get_units first to get current unit IDs — never guess them.",
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
                                "description": "ID of the unit to command. Must come from get_units results — never guess.",
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
            "description": "Set what a city should produce. Always call get_city_production first to see available options and their IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "ID of the city. Must come from get_cities results — never guess.",
                    },
                    "order_type": {
                        "type": "integer",
                        "description": "Production type: 0=unit, 1=building, 2=wonder, 3=process",
                    },
                    "item_id": {
                        "type": "integer",
                        "description": "ID from get_city_production results. Never guess — always call get_city_production first.",
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
            "description": "Select a technology to research. Use tech_id from get_available_techs. On failure, error.code is one of: ALREADY_RESEARCHED (pick a different tech), PREREQS_NOT_MET (need earlier techs first), INVALID_TECH (bad ID), CANNOT_RESEARCH (mod restriction). Error includes tech_name for confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tech_id": {
                        "type": "integer",
                        "description": "ID of the technology to research. Get valid IDs from get_available_techs — never guess.",
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
            "description": "End your turn. Will fail if there are unresolved blockers. If blocked by ENDTURN_BLOCKING_UNITS, the error includes blocking_units[] with unit_id and moves_left — a unit still has movement remaining. Either move it again to exhaust its moves, or call send_action with unit_skip to dismiss it for this turn.",
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
            "name": "city_capture_decision",
            "description": "Make a decision about a captured city: puppet, annex, raze, destroy, or liberate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_id": {
                        "type": "integer",
                        "description": "ID of the captured city",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["puppet", "annex", "raze", "destroy", "liberate"],
                        "description": "What to do with the city",
                    },
                    "liberate_to": {
                        "type": "integer",
                        "description": "Player ID to liberate the city to (required when action is 'liberate')",
                    },
                },
                "required": ["city_id", "action"],
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
