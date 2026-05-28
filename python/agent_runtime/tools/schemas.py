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
            "description": "Get all units owned by the player with their IDs, positions, types, moves remaining, territory_owner (player ID of the tile's owner, -1 if unowned), is_trespassing (in foreign territory without open borders), is_embarked (on water as embarked unit), activity (AWAKE/MISSION/SLEEP/HOLD/HEAL/SENTRY), and for MISSION units: mission (XML type name e.g. MISSION_BUILD, MISSION_MOVE_TO), mission_target {x,y} for move missions, build_name for build missions. Do NOT issue new commands to units with activity=MISSION.",
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
            "description": "Get available production options (units, buildings, wonders, processes) for a specific city. Returns item IDs needed for set_city_production. Also returns current_production (what is already being built, or null). Do not call set_city_production unless you intend to replace the current production.",
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
            "description": "Get structured JSON tile data for all revealed tiles: terrain, feature, resource, improvement, route, territory_owner, units, city. Use this for strategic analysis and decisions across the full known map.",
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
            "name": "move_unit",
            "description": "Move a unit to target coordinates using A* pathfinding. Multi-turn mission — the unit will continue moving until it arrives. Always call get_units first to get current unit IDs — never guess them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "integer",
                        "description": "ID of the unit to move. Must come from get_units results.",
                    },
                    "to": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Target coordinates [x, y].",
                    },
                },
                "required": ["unit_id", "to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_found_city",
            "description": "Found a city at the settler's current position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "integer",
                        "description": "ID of the settler unit.",
                    },
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_sleep",
            "description": "Put a unit to sleep/fortify indefinitely.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "integer", "description": "ID of the unit."},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_skip",
            "description": "Skip a unit's turn (hold position this turn only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "integer", "description": "ID of the unit."},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_alert",
            "description": "Put a unit on alert — it will wake automatically if an enemy approaches.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "integer", "description": "ID of the unit."},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_fortify",
            "description": "Fortify a military unit, giving it a defensive bonus that grows over time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "integer", "description": "ID of the unit."},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_heal",
            "description": "Order a unit to heal in place.",
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {"type": "integer", "description": "ID of the unit."},
                },
                "required": ["unit_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unit_build",
            "description": (
                "Order a worker to build an improvement (farm, mine, road, etc.) at its current tile. "
                "Call get_unit_build_options first to see available build_type IDs and where the worker needs to be. "
                "Move the worker to the target tile before calling this. "
                "Building takes multiple turns — the worker will continue automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "unit_id": {
                        "type": "integer",
                        "description": "ID of the worker unit. Must come from get_units results.",
                    },
                    "build_type": {
                        "type": "integer",
                        "description": "Build type ID from get_unit_build_options. Never guess.",
                    },
                },
                "required": ["unit_id", "build_type"],
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
            "description": "End your turn. Will fail if there are unresolved blockers. If blocked by ENDTURN_BLOCKING_UNITS, the error includes blocking_units[] with unit_id and moves_left — a unit still has movement remaining. Either move it again to exhaust its moves, or call unit_skip(unit_id) to dismiss it for this turn.",
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
    # === Self-management ===
    {
        "type": "function",
        "function": {
            "name": "halt",
            "description": "Stop the runner immediately and alert the developers. Use when you are genuinely stuck and cannot make progress — e.g. a tool always fails, the game state is inconsistent, or you have tried the same action multiple times without effect. This ends the session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "What is wrong and why you cannot continue. Be specific: name the tool, action, or state that is broken.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wish",
            "description": "Record a capability you need but don't have — a missing tool, confusing interface, or information gap. Does not stop the turn. Developers will see this.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "What you wish existed. Be specific: name the action you want to take, what inputs it would need, and what you'd use it for right now.",
                    },
                },
                "required": ["description"],
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


def get_tool_names() -> list[str]:
    """Get list of all tool names."""
    return [tool["function"]["name"] for tool in TOOL_SCHEMAS]
