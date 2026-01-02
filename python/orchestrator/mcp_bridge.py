"""
MCP Bridge - Integrates MCP Server with Orchestrator

This module provides an integrated mode where the orchestrator runs alongside
the MCP server, allowing LLMs to control the game through MCP tools while
the orchestrator manages the pipe communication with the Civ V DLL.
"""

import asyncio
import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from jsonschema import Draft202012Validator

from .mcp_server import CivMCPServer

logger = logging.getLogger(__name__)


class MCPBridge:
    """Bridge between orchestrator pipe transport and MCP server."""

    def __init__(self, transport, repo_root: Path, validate: bool = True):
        """
        Initialize the MCP bridge.

        Args:
            transport: Transport object (WindowsPipeTransport or StdIOTransport)
            repo_root: Repository root path for loading schemas
            validate: Whether to validate state and actions against schemas
        """
        self.transport = transport
        self.repo_root = repo_root
        self.validate = validate

        # Create MCP server instance
        self.mcp_server = CivMCPServer()

        # Validators
        self.state_validator: Optional[Draft202012Validator] = None
        self.action_validator: Optional[Draft202012Validator] = None

        if validate:
            try:
                self.state_validator = self._load_validator("state.schema.json")
                self.action_validator = self._load_validator("actions.schema.json")
            except Exception as e:
                logger.warning(f"Could not load validators: {e}")

        # Threading for async MCP server
        self.mcp_thread: Optional[threading.Thread] = None
        self.running = False

    def _load_validator(self, schema_name: str) -> Draft202012Validator:
        """Load a JSON schema validator."""
        schema_path = self.repo_root / "schemas" / schema_name
        with schema_path.open("r") as f:
            schema = json.load(f)
        return Draft202012Validator(schema)

    async def _run_mcp_server(self):
        """Run the MCP server in async context."""
        logger.info("Starting MCP server...")
        await self.mcp_server.run()

    def start_mcp_server(self):
        """Start the MCP server in a separate thread."""
        def run_async_server():
            asyncio.run(self._run_mcp_server())

        self.mcp_thread = threading.Thread(target=run_async_server, daemon=True)
        self.mcp_thread.start()
        logger.info("MCP server thread started")

    def process_turn(self) -> bool:
        """
        Process one turn: read state from DLL, update MCP, get actions, send back.

        Returns:
            True if turn was processed, False if pipe closed/error
        """
        # Read state from DLL
        line = self.transport.read_line()
        if line is None or line == "":
            logger.info("Pipe closed or no data")
            return False

        line = line.strip()
        if not line:
            return True  # Empty line, continue

        # Parse and validate state
        try:
            state = json.loads(line)

            if self.state_validator:
                self.state_validator.validate(state)

            logger.info(f"Received state: turn {state.get('data', {}).get('turn', '?')}")

            # Update MCP server with new state
            self.mcp_server.update_state(state)

        except Exception as e:
            logger.error(f"Error processing state: {e}")
            error_response = {"error": "invalid_state", "detail": str(e)}
            self.transport.write_line(json.dumps(error_response))
            return True  # Continue despite error

        # Get pending actions from MCP server
        pending_actions = self.mcp_server.get_pending_actions()

        # Build action response
        turn_number = state.get("data", {}).get("turn", 0)
        action_response = {
            "turn": turn_number,
            "actions": pending_actions,
            "notes": f"MCP server actions: {len(pending_actions)} queued"
        }

        # Validate actions
        if self.action_validator:
            try:
                self.action_validator.validate(action_response)
            except Exception as e:
                logger.error(f"Action validation failed: {e}")
                # Send safe no-op instead
                action_response = {
                    "turn": turn_number,
                    "actions": [],
                    "notes": f"validation_error: {e}"
                }

        # Send actions back to DLL
        self.transport.write_line(json.dumps(action_response))
        logger.info(f"Sent {len(pending_actions)} actions to DLL")

        return True

    def run(self, once: bool = False):
        """
        Run the bridge main loop.

        Args:
            once: If True, process only one turn then exit
        """
        self.running = True

        # Start MCP server in background
        # Note: We don't actually start it here because it needs stdio,
        # which conflicts with our pipe transport. In a real implementation,
        # the MCP server would need a different transport (HTTP, etc.)
        # For now, we just run the orchestrator loop and the MCP server
        # provides the state/action queuing mechanism.

        logger.info("MCP Bridge started, processing turns...")

        try:
            while self.running:
                if not self.process_turn():
                    break

                if once:
                    break

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt, shutting down...")
        finally:
            self.running = False
            logger.info("MCP Bridge stopped")


def run_integrated_mode(transport, repo_root: Path, once: bool = False):
    """
    Run orchestrator in integrated MCP mode.

    This creates a bridge that connects the DLL pipe transport to the MCP server,
    allowing LLMs to control the game via MCP tools.

    Args:
        transport: Transport object for DLL communication
        repo_root: Repository root path
        once: If True, process only one turn then exit
    """
    bridge = MCPBridge(transport, repo_root)
    bridge.run(once=once)
