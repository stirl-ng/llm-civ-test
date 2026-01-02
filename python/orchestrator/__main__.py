from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from jsonschema import Draft202012Validator

from agent_runtime import Agent, get_model, build_tools
from agent_runtime.strategies.vanilla import VanillaStrategy

from .formatting import format_message
from .pipe_server import NamedPipeServer


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_schema(repo_root: Path, name: str) -> Dict[str, Any]:
    with (repo_root / "schemas" / name).open("r", encoding="utf-8") as f:
        return json.load(f)


def _validator(repo_root: Path, name: str):
    return Draft202012Validator(_load_schema(repo_root, name))


def _build_strategy(cfg: Dict[str, Any]):
    name = (cfg.get("name") or cfg.get("kind") or "vanilla").lower()
    if name == "vanilla":
        return VanillaStrategy(temperature=cfg.get("temperature", 0.2))
    raise ValueError(f"Unsupported strategy: {name}")


class Transport:
    def read_line(self) -> Optional[str]:  # pragma: no cover - IO wrapper
        raise NotImplementedError

    def write_line(self, s: str) -> None:  # pragma: no cover - IO wrapper
        raise NotImplementedError


class StdIOTransport(Transport):
    def __init__(self):
        self.reader = sys.stdin
        self.writer = sys.stdout

    def read_line(self) -> Optional[str]:
        return self.reader.readline()

    def write_line(self, s: str) -> None:
        self.writer.write(s)
        if not s.endswith("\n"):
            self.writer.write("\n")
        self.writer.flush()


class WindowsPipeTransport(Transport):
    def __init__(self, pipe_name: str, retry_seconds: float = 0.5, timeout: float = 30.0):
        self.pipe_name = pipe_name
        deadline = time.time() + timeout
        last_err: Optional[Exception] = None
        fh: Optional[io.BufferedRandom] = None
        while time.time() < deadline:
            try:
                # Open as binary read/write, unbuffered (0), then wrap buffered
                raw = open(pipe_name, mode="r+b", buffering=0)
                fh = io.BufferedRandom(raw)
                break
            except Exception as e:  # pragma: no cover - platform dependent
                last_err = e
                time.sleep(retry_seconds)
        if fh is None:
            raise RuntimeError(f"Failed to open pipe {pipe_name}: {last_err}")
        self.fh = fh

    def read_line(self) -> Optional[str]:  # pragma: no cover - platform dependent
        data = self.fh.readline()
        if not data:
            return None
        try:
            return data.decode("utf-8")
        except Exception:
            return data.decode("utf-8", errors="replace")

    def write_line(self, s: str) -> None:  # pragma: no cover - platform dependent
        if not s.endswith("\n"):
            s = s + "\n"
        self.fh.write(s.encode("utf-8"))
        self.fh.flush()


def build_agent(cfg: Dict[str, Any]) -> Agent:
    model = get_model(cfg.get("backend", {}))
    tools = build_tools(cfg.get("tools", []))
    strategy = _build_strategy(cfg.get("strategy", {}))
    return Agent(model=model, tools=tools, strategy=strategy)


DEFAULT_DEBUG_PIPE = r"\\.\pipe\CivVPGameState"


def run_debug_server(pipe_path: str, raw_mode: bool = False) -> None:
    """Run a debug pipe server that displays incoming messages.

    This creates a named pipe server and prints all messages received from
    the Civ V DLL. Useful for debugging and inspecting game state.

    Args:
        pipe_path: The named pipe path to create
        raw_mode: If True, print raw JSON; if False, format nicely
    """
    print("=" * 60)
    print("Civ V LLM Bridge - Debug Pipe Server")
    print("=" * 60)
    print(f"Pipe: {pipe_path}")
    print(f"Mode: {'raw JSON' if raw_mode else 'formatted'}")
    print("=" * 60)
    print()

    def on_message(data: bytes) -> Optional[bytes]:
        try:
            decoded = data.decode("utf-8").rstrip("\r\n")
        except UnicodeDecodeError:
            decoded = data.hex()
        output = format_message(decoded, raw_mode=raw_mode)
        print(output, flush=True)
        return None

    server = NamedPipeServer(pipe_path, on_message)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nCtrl+C pressed. Exiting.", flush=True)
        server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Civ V Orchestrator")
    parser.add_argument("--agent-config", help="YAML config describing backend/tools/strategy")
    parser.add_argument("--pipe", help="Override named pipe path")
    parser.add_argument("--stdio", action="store_true", help="Use stdin/stdout instead of pipe (for testing)")
    parser.add_argument("--once", action="store_true", help="Process only one message then exit")
    parser.add_argument("--debug", action="store_true", help="Run as debug server: display messages without agent processing")
    parser.add_argument("--raw", action="store_true", help="In debug mode, print raw JSON instead of formatted output")
    args = parser.parse_args()

    # Debug mode: just display messages, don't run agent
    if args.debug:
        pipe = args.pipe or DEFAULT_DEBUG_PIPE
        run_debug_server(pipe, raw_mode=args.raw)
        return

    repo_root = Path(__file__).resolve().parents[2]

    # Load agent config (reuse experiment schema shape)
    agent_cfg: Dict[str, Any] = {}
    if args.agent_config:
        agent_cfg = _load_yaml(Path(args.agent_config))
    elif (repo_root / "python" / "configs" / "experiments" / "minimal.yaml").exists():
        agent_cfg = _load_yaml(repo_root / "python" / "configs" / "experiments" / "minimal.yaml")

    # Validate config with experiment schema (subset used here)
    try:
        Draft202012Validator(_load_schema(repo_root, "experiment.schema.json")).validate(agent_cfg)
    except Exception:
        # Keep permissive to allow simple runs without full config
        pass

    agent = build_agent(agent_cfg)

    # Set up transports
    if args.stdio:
        transport: Transport = StdIOTransport()
        print("[orchestrator] Using StdIO transport", file=sys.stderr)
    else:
        pipe = (
            args.pipe
            or os.environ.get("CIVV_PIPE")
            or agent_cfg.get("orchestrator", {}).get("pipe")
            or r"\\.\pipe\civv_llm"
        )
        transport = WindowsPipeTransport(pipe)
        print(f"[orchestrator] Connected to pipe: {pipe}", file=sys.stderr)

    # Load schemas for I/O validation
    state_v = _validator(repo_root, "state.schema.json")
    action_v = _validator(repo_root, "actions.schema.json")

    # Main loop
    while True:
        line = transport.read_line()
        if line is None or line == "":
            # End of stream or pipe broken
            break
        line = line.strip()
        if not line:
            continue
        try:
            state = json.loads(line)
            state_v.validate(state)
        except Exception as e:
            err = {"error": "invalid_state", "detail": str(e)}
            transport.write_line(json.dumps(err))
            if args.once:
                break
            continue

        actions = agent.step(state)
        try:
            action_v.validate(actions)
        except Exception as e:
            # Ensure we never crash the game: send a no-op with error note
            actions = {
                "turn": state.get("turn", 0),
                "actions": [],
                "notes": f"orchestrator_validation_error: {e}",
            }
        transport.write_line(json.dumps(actions))
        if args.once:
            break


if __name__ == "__main__":
    main()

