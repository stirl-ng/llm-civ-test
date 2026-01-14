from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import yaml
from jsonschema import Draft202012Validator

from agent_runtime import Agent, get_model, build_tools
from agent_runtime.strategies.vanilla import VanillaStrategy


def load_schema(python_root: Path, name: str) -> Dict[str, Any]:
    schema_path = python_root / "schemas" / name
    with schema_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(obj: Dict[str, Any], schema: Dict[str, Any]) -> None:
    Draft202012Validator(schema).validate(obj)


def load_config(config_arg: str) -> Dict[str, Any]:
    """
    Load config from a path or short name.
    
    If config_arg is a short name (no path separators), looks for it in
    python/configs/experiments/{name}.yaml. Otherwise treats it as a file path.
    """
    config_path = Path(config_arg)
    
    # If it's not an absolute path and has no path separators, treat as short name
    if not config_path.is_absolute() and "/" not in config_arg and "\\" not in config_arg:
        # Resolve relative to python/configs/experiments/
        python_root = Path(__file__).resolve().parent.parent
        config_path = python_root / "configs" / "experiments" / f"{config_arg}.yaml"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_strategy(cfg: Dict[str, Any]):
    name = (cfg.get("name") or cfg.get("kind") or "vanilla").lower()
    if name == "vanilla":
        return VanillaStrategy(temperature=cfg.get("temperature", 0.2))
    raise ValueError(f"Unsupported strategy: {name}")


def dry_run(agent: Agent) -> None:
    # Minimal fake state to exercise the pipeline; real runs come from orchestrator
    state = {"turn": 1}
    actions = agent.step(state)
    print(json.dumps({"agent": agent.name(), "actions": actions}, indent=2))


def call_orchestrator_tool(base_url: str, tool: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Call an orchestrator tool via HTTP."""
    try:
        response = requests.post(
            f"{base_url}/tool",
            json={"tool": tool, "arguments": arguments},
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to call orchestrator tool {tool}: {e}") from e


def check_orchestrator_health(base_url: str) -> bool:
    """Check if orchestrator is running."""
    try:
        response = requests.get(f"{base_url}/health", timeout=5.0)
        response.raise_for_status()
        return response.json().get("status") == "ok"
    except requests.exceptions.RequestException:
        return False


def get_game_state(base_url: str) -> Optional[Dict[str, Any]]:
    """Get current game state from orchestrator."""
    try:
        result = call_orchestrator_tool(base_url, "get_game_state", {})
        if result.get("status") == "error":
            return None
        return result.get("result", {})
    except Exception:
        return None


def send_actions_to_orchestrator(base_url: str, actions: list, notes: str = "") -> Dict[str, Any]:
    """Send actions to orchestrator."""
    if not actions:
        return {"status": "success", "message": "No actions to send"}
    
    # Use send_actions if available, otherwise send individually
    try:
        result = call_orchestrator_tool(base_url, "send_actions", {
            "actions": actions,
            "notes": notes
        })
        return result
    except RuntimeError:
        # Fallback to individual send_action calls
        results = []
        for action in actions:
            try:
                result = call_orchestrator_tool(base_url, "send_action", {
                    "action": action,
                    "notes": notes if len(actions) == 1 else ""
                })
                results.append(result)
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
        return {"status": "success", "results": results}


def end_turn(base_url: str, turn: int) -> Dict[str, Any]:
    """End the current turn."""
    return call_orchestrator_tool(base_url, "end_turn", {"turn": turn})


def run_game_loop(agent: Agent, base_url: str, poll_interval: float = 2.0) -> None:
    """Main game loop that polls for turns and processes them."""
    print(f"Connecting to orchestrator at {base_url}...")
    
    # Wait for orchestrator to be available
    max_wait = 30
    waited = 0
    while not check_orchestrator_health(base_url):
        if waited >= max_wait:
            raise RuntimeError(f"Orchestrator not available at {base_url} after {max_wait} seconds")
        print(f"Waiting for orchestrator... ({waited}/{max_wait}s)")
        time.sleep(1.0)
        waited += 1
    
    print("Orchestrator connected!")
    print(f"Agent: {agent.name()}")
    print("Waiting for game to start...")
    
    last_turn: Optional[int] = None
    game_over = False
    
    try:
        while not game_over:
            # Poll for game state
            state = get_game_state(base_url)
            
            if state is None:
                # No game state available yet, wait and retry
                time.sleep(poll_interval)
                continue
            
            # Extract turn number
            current_turn = state.get("turn")
            
            # Check if this is a new turn
            if current_turn is None:
                # Game not started yet
                time.sleep(poll_interval)
                continue
            
            if last_turn is not None and current_turn == last_turn:
                # Same turn, wait for next turn
                time.sleep(poll_interval)
                continue
            
            # New turn detected!
            print(f"\n{'='*60}")
            print(f"Turn {current_turn} started")
            print(f"{'='*60}")
            
            last_turn = current_turn
            
            # Process the turn
            try:
                # Get agent's actions for this turn
                print("Getting agent decisions...")
                action_result = agent.step(state)
                
                # Extract actions from result
                actions = action_result.get("actions", [])
                notes = action_result.get("notes", "")
                
                if notes:
                    print(f"Agent notes: {notes}")
                
                # Send actions if any
                if actions:
                    print(f"Sending {len(actions)} action(s)...")
                    if isinstance(actions, list):
                        send_result = send_actions_to_orchestrator(base_url, actions, notes)
                    else:
                        # Single action
                        send_result = send_actions_to_orchestrator(base_url, [actions], notes)
                    
                    if send_result.get("status") == "error":
                        print(f"Warning: Error sending actions: {send_result.get('error', 'Unknown error')}")
                    else:
                        print("Actions sent successfully")
                else:
                    print("No actions to send")
                
                # End the turn
                print(f"Ending turn {current_turn}...")
                end_result = end_turn(base_url, current_turn)
                
                if end_result.get("status") == "error":
                    error_msg = end_result.get("error", "Unknown error")
                    print(f"Warning: Error ending turn: {error_msg}")
                    # Check if it's a game over condition
                    if "game" in error_msg.lower() and "over" in error_msg.lower():
                        game_over = True
                else:
                    print(f"Turn {current_turn} ended successfully")
                
            except KeyboardInterrupt:
                print("\nInterrupted by user")
                game_over = True
            except Exception as e:
                print(f"Error processing turn: {e}")
                # Continue loop, but log the error
                import traceback
                traceback.print_exc()
                time.sleep(poll_interval)
            
            # Small delay before next poll
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\nGame loop interrupted by user")
    except Exception as e:
        print(f"Fatal error in game loop: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    print("Game loop ended")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Civ V LLM experiments")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to experiment YAML config or short name (e.g., 'gemini' for python/configs/experiments/gemini.yaml)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without orchestrator, just one step")
    args = parser.parse_args()

    python_root = Path(__file__).resolve().parent.parent
    cfg = load_config(args.config)

    # Validate experiment config
    exp_schema = load_schema(python_root, "experiment.schema.json")
    validate(cfg, exp_schema)

    # Build components
    model = get_model(cfg.get("backend", {}))
    tools = build_tools(cfg.get("tools", []))
    strategy = build_strategy(cfg.get("strategy", {}))
    agent = Agent(model=model, tools=tools, strategy=strategy)

    if args.dry_run:
        dry_run(agent)
        return

    # Get orchestrator configuration
    orchestrator_cfg = cfg.get("orchestrator", {})
    pipe_name = orchestrator_cfg.get("pipe", r"\\.\pipe\civv_llm")
    base_url = orchestrator_cfg.get("url", "http://localhost:8765")
    poll_interval = orchestrator_cfg.get("poll_interval", 2.0)
    
    print(f"Orchestrator pipe: {pipe_name}")
    print(f"Orchestrator URL: {base_url}")
    print(f"Poll interval: {poll_interval}s")
    print()
    
    # Run the game loop
    run_game_loop(agent, base_url, poll_interval)


if __name__ == "__main__":
    main()

