#!/usr/bin/env python3
"""Launch orchestrator + agent runners.

On Windows: opens a separate cmd window per process.
On Linux/Mac: uses a tmux session.

Usage:
  python launch.py                  # interactive config selection
  python launch.py gemini           # single runner, no prompt
  python launch.py gemini openai    # two runners
"""
import subprocess
import sys
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent / "configs" / "experiments"
SESSION = "civ"


def available_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def pick_configs() -> list[str]:
    configs = available_configs()
    print("Available configs:")
    for i, name in enumerate(configs, 1):
        print(f"  {i}) {name}")
    raw = input("Select (numbers or names, space-separated): ").strip().split()

    selected = []
    for token in raw:
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(configs):
                selected.append(configs[idx])
            else:
                print(f"  Skipping invalid index: {token}")
        elif token in configs:
            selected.append(token)
        else:
            print(f"  Unknown config: {token}")
    return selected


# ── Windows launcher ──────────────────────────────────────────────────────────

def launch_windows(configs: list[str]) -> None:
    python_dir = Path(sys.executable).parent
    here = Path(__file__).parent

    def start(title: str, cmd: str) -> None:
        # `start` requires shell=True on Windows
        subprocess.Popen(
            f'start "{title}" cmd /k "cd /d {here} && {cmd}"',
            shell=True,
        )

    start("orchestrator", f'"{python_dir}\\python.exe" -m orchestrator')
    for cfg in configs:
        start(f"agent-{cfg}", f'"{python_dir}\\python.exe" -m agent_runtime --config {cfg}')

    print("Launched in separate windows.")


# ── tmux launcher ─────────────────────────────────────────────────────────────

def tmux(args: list[str]) -> None:
    subprocess.run(["tmux"] + args, check=True)


def session_exists() -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", SESSION],
        capture_output=True,
    )
    return result.returncode == 0


def launch_tmux(configs: list[str]) -> None:
    if session_exists():
        print(f"tmux session '{SESSION}' already exists — kill it first with: tmux kill-session -t {SESSION}")
        sys.exit(1)

    orch_cmd = "python -m orchestrator"
    runner_cmd = lambda cfg: f"python -m agent_runtime --config {cfg}"

    tmux(["new-session", "-d", "-s", SESSION, "-n", "orch", "-x", "220", "-y", "50"])
    tmux(["send-keys", "-t", f"{SESSION}:orch", orch_cmd, "Enter"])

    for cfg in configs:
        tmux(["split-window", "-h", "-t", f"{SESSION}:orch"])
        tmux(["send-keys", "-t", f"{SESSION}:orch", runner_cmd(cfg), "Enter"])

    tmux(["select-layout", "-t", f"{SESSION}:orch", "even-horizontal"])
    tmux(["attach-session", "-t", SESSION])


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    configs = sys.argv[1:] or pick_configs()
    if not configs:
        print("No configs selected.")
        sys.exit(1)

    unknown = [c for c in configs if c not in available_configs()]
    if unknown:
        print(f"Unknown configs: {', '.join(unknown)}")
        sys.exit(1)

    print(f"Launching: orchestrator + {configs}")
    if sys.platform == "win32":
        launch_windows(configs)
    else:
        launch_tmux(configs)


if __name__ == "__main__":
    main()
