"""
MCP Server for Civilization V LLM Orchestrator

Provides tools for LLMs to:
- Query game state
- Send commands to the DLL
- Get available actions/choices
- Format game data for analysis
"""

import asyncio
import json
import logging
from typing import Any, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .formatting import format_game_state, format_message

logger = logging.getLogger(__name__)


class CivMCPServer:
    """MCP Server that bridges LLM requests to Civ V orchestrator."""

    def __init__(self):
        self.server = Server("civ5-orchestrator")
        self.current_state: Optional[dict[str, Any]] = None
        self.last_action_result: Optional[dict[str, Any]] = None
        self.pending_actions: list[dict[str, Any]] = []

        # Register all tools
        self._register_tools()

    def _register_tools(self):
        """Register all available MCP tools."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List all available tools for controlling Civilization V."""
            return [
                Tool(
                    name="get_game_state",
                    description="Get the current game state. Optionally filter by category (e.g., 'game_level', 'cities', 'units', 'technology', 'diplomacy')",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "description": "Optional category to filter (game_level, cities, units, technology, diplomacy, etc.)",
                            },
                            "format": {
                                "type": "string",
                                "enum": ["json", "human_readable"],
                                "description": "Output format: 'json' or 'human_readable'",
                                "default": "json"
                            }
                        },
                    },
                ),
                Tool(
                    name="send_action",
                    description="Send an action/command to the game. Actions can include unit commands, production orders, research choices, policy selections, etc.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "object",
                                "description": "The action object to send to the game (e.g., {'research': 'TECH_POTTERY'})",
                            },
                            "notes": {
                                "type": "string",
                                "description": "Optional notes about why this action was chosen",
                            }
                        },
                        "required": ["action"],
                    },
                ),
                Tool(
                    name="send_actions",
                    description="Send multiple actions at once. Useful for coordinating complex multi-action turns.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "actions": {
                                "type": "array",
                                "description": "Array of action objects",
                                "items": {"type": "object"}
                            },
                            "notes": {
                                "type": "string",
                                "description": "Optional notes about the strategy",
                            }
                        },
                        "required": ["actions"],
                    },
                ),
                Tool(
                    name="get_cities",
                    description="Get detailed information about all cities, including production, buildings, population, etc.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "city_id": {
                                "type": "integer",
                                "description": "Optional: Get info for specific city ID only",
                            }
                        },
                    },
                ),
                Tool(
                    name="get_units",
                    description="Get information about all military and civilian units, including positions, health, and available commands.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "unit_id": {
                                "type": "integer",
                                "description": "Optional: Get info for specific unit ID only",
                            }
                        },
                    },
                ),
                Tool(
                    name="get_tech_tree",
                    description="Get technology tree status: researched techs, current research, available options, and costs.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_diplomacy",
                    description="Get diplomatic status with all known civilizations, including relationships, wars, and agreements.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_available_choices",
                    description="Get all pending decisions that need to be made (tech choice, policy choice, production choices, etc.)",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_victory_progress",
                    description="Get progress toward all victory conditions (Domination, Science, Culture, Diplomatic, Time)",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="get_resources",
                    description="Get strategic and luxury resources: available quantities, sources, and trades.",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                    },
                ),
                Tool(
                    name="format_state",
                    description="Get a human-readable formatted version of the game state for analysis.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "raw": {
                                "type": "boolean",
                                "description": "Include raw JSON alongside formatted output",
                                "default": False
                            }
                        },
                    },
                ),
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            """Handle tool calls from the LLM."""
            try:
                result = await self._execute_tool(name, arguments)
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
            except Exception as e:
                logger.error(f"Error executing tool {name}: {e}", exc_info=True)
                return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a specific tool and return results."""

        if name == "get_game_state":
            return self._get_game_state(
                category=arguments.get("category"),
                format_type=arguments.get("format", "json")
            )

        elif name == "send_action":
            return self._send_action(
                action=arguments["action"],
                notes=arguments.get("notes", "")
            )

        elif name == "send_actions":
            return self._send_actions(
                actions=arguments["actions"],
                notes=arguments.get("notes", "")
            )

        elif name == "get_cities":
            return self._get_cities(city_id=arguments.get("city_id"))

        elif name == "get_units":
            return self._get_units(unit_id=arguments.get("unit_id"))

        elif name == "get_tech_tree":
            return self._get_tech_tree()

        elif name == "get_diplomacy":
            return self._get_diplomacy()

        elif name == "get_available_choices":
            return self._get_available_choices()

        elif name == "get_victory_progress":
            return self._get_victory_progress()

        elif name == "get_resources":
            return self._get_resources()

        elif name == "format_state":
            return self._format_state(raw=arguments.get("raw", False))

        else:
            return {"error": f"Unknown tool: {name}"}

    def update_state(self, state: dict[str, Any]) -> None:
        """Update the current game state (called by orchestrator)."""
        self.current_state = state
        logger.info(f"Game state updated: turn {state.get('data', {}).get('turn', '?')}")

    def _get_game_state(self, category: Optional[str] = None, format_type: str = "json") -> dict[str, Any]:
        """Get current game state, optionally filtered by category."""
        if not self.current_state:
            return {"error": "No game state available"}

        state = self.current_state.get("data", {})

        # Filter by category if requested
        if category:
            if category in state:
                state = {category: state[category]}
            else:
                return {"error": f"Category '{category}' not found in state", "available": list(state.keys())}

        # Format if requested
        if format_type == "human_readable":
            formatted = format_game_state(state)
            return {"formatted": formatted, "json": state}

        return state

    def _send_action(self, action: dict[str, Any], notes: str = "") -> dict[str, Any]:
        """Queue a single action to be sent to the game."""
        self.pending_actions.append(action)
        logger.info(f"Action queued: {action}")
        return {
            "status": "queued",
            "action": action,
            "notes": notes,
            "total_pending": len(self.pending_actions)
        }

    def _send_actions(self, actions: list[dict[str, Any]], notes: str = "") -> dict[str, Any]:
        """Queue multiple actions to be sent to the game."""
        self.pending_actions.extend(actions)
        logger.info(f"{len(actions)} actions queued")
        return {
            "status": "queued",
            "action_count": len(actions),
            "notes": notes,
            "total_pending": len(self.pending_actions)
        }

    def get_pending_actions(self) -> list[dict[str, Any]]:
        """Get all pending actions (called by orchestrator)."""
        actions = self.pending_actions[:]
        self.pending_actions.clear()
        return actions

    def _get_cities(self, city_id: Optional[int] = None) -> dict[str, Any]:
        """Get city information."""
        if not self.current_state:
            return {"error": "No game state available"}

        cities = self.current_state.get("data", {}).get("cities", [])

        if city_id is not None:
            city = next((c for c in cities if c.get("id") == city_id), None)
            if city:
                return city
            return {"error": f"City {city_id} not found"}

        return {"cities": cities, "count": len(cities)}

    def _get_units(self, unit_id: Optional[int] = None) -> dict[str, Any]:
        """Get unit information."""
        if not self.current_state:
            return {"error": "No game state available"}

        units = self.current_state.get("data", {}).get("units", [])

        if unit_id is not None:
            unit = next((u for u in units if u.get("id") == unit_id), None)
            if unit:
                return unit
            return {"error": f"Unit {unit_id} not found"}

        return {"units": units, "count": len(units)}

    def _get_tech_tree(self) -> dict[str, Any]:
        """Get technology tree information."""
        if not self.current_state:
            return {"error": "No game state available"}

        return self.current_state.get("data", {}).get("technology", {})

    def _get_diplomacy(self) -> dict[str, Any]:
        """Get diplomacy information."""
        if not self.current_state:
            return {"error": "No game state available"}

        return self.current_state.get("data", {}).get("diplomacy", {})

    def _get_available_choices(self) -> dict[str, Any]:
        """Get all pending choices/decisions."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        choices = {}

        # Extract various choice requirements
        if data.get("needs_tech_choice"):
            choices["tech"] = data.get("available_techs", [])

        if data.get("needs_policy_choice"):
            choices["policy"] = data.get("available_policies", [])

        if data.get("needs_production_choice"):
            choices["production"] = data.get("cities_needing_production", [])

        if data.get("needs_religion_choice"):
            choices["religion"] = data.get("religion_options", {})

        if data.get("needs_trade_route_assignment"):
            choices["trade_routes"] = data.get("available_trade_routes", [])

        return {"pending_choices": choices, "has_choices": len(choices) > 0}

    def _get_victory_progress(self) -> dict[str, Any]:
        """Get victory condition progress."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        return {
            "victory_conditions": data.get("victory_conditions", []),
            "victory_progress": data.get("victory_progress", {})
        }

    def _get_resources(self) -> dict[str, Any]:
        """Get resource information."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        return {
            "strategic": data.get("strategic_resources", {}),
            "luxury": data.get("luxury_resources", {}),
            "total": data.get("resources", {})
        }

    def _format_state(self, raw: bool = False) -> dict[str, Any]:
        """Get formatted game state."""
        if not self.current_state:
            return {"error": "No game state available"}

        data = self.current_state.get("data", {})
        formatted = format_game_state(data)

        if raw:
            return {"formatted": formatted, "raw": data}

        return {"formatted": formatted}

    async def run(self):
        """Run the MCP server using stdio transport."""
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP Server starting on stdio...")
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def run_mcp_server():
    """Entry point for running the MCP server."""
    server = CivMCPServer()
    await server.run()


if __name__ == "__main__":
    # Run standalone MCP server
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    asyncio.run(run_mcp_server())
