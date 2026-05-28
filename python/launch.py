#!/usr/bin/env python3
"""Launch orchestrator + agent runners.

On Windows: background processes logging to files. Stop with: python launch.py stop
On Linux/Mac: uses a tmux session.

Usage:
  python launch.py                        # interactive config selection
  python launch.py gemini                 # single runner, no prompt
  python launch.py gemini openai          # two runners
  python launch.py gemini --observer obs  # runner + observer
  python launch.py stop                   # kill previously launched processes (Windows)
"""
import subprocess
import sys
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent / "configs" / "experiments"
OBSERVER_CONFIGS_DIR = Path(__file__).parent / "configs" / "observer"
LOGS_DIR = Path(__file__).parent / "logs"
PID_FILE = LOGS_DIR / "pids.txt"
SESSION = "civ"


def available_configs() -> list[str]:
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.yaml"))


def available_observer_configs() -> list[str]:
    return sorted(p.stem for p in OBSERVER_CONFIGS_DIR.glob("*.yaml"))


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


def pick_observer() -> str | None:
    configs = available_observer_configs()
    if not configs:
        return None
    print("Observer configs:")
    print(f"  0) none")
    for i, name in enumerate(configs, 1):
        print(f"  {i}) {name}")
    raw = input("Select observer (Enter to skip): ").strip()
    if not raw or raw == "0" or raw.lower() == "none":
        return None
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(configs):
            return configs[idx]
        print(f"  Invalid index — skipping observer")
        return None
    if raw in configs:
        return raw
    print(f"  Unknown config '{raw}' — skipping observer")
    return None


# ── Windows launcher ──────────────────────────────────────────────────────────

def launch_windows(configs: list[str], observer_cfg: str | None = None) -> None:
    python_exe = str(Path(sys.executable))
    here = Path(__file__).parent
    LOGS_DIR.mkdir(exist_ok=True)

    pids = []

    def start(label: str, args: list[str], log_path: Path) -> None:
        log_f = open(log_path, "w", buffering=1)
        proc = subprocess.Popen(
            args,
            stdout=log_f,
            stderr=log_f,
            cwd=here,
        )
        pids.append((label, proc.pid))
        print(f"  {label} (pid {proc.pid}) → {log_path}")

    start("orchestrator", [python_exe, "-u", "-m", "orchestrator"], LOGS_DIR / "orchestrator.log")
    for cfg in configs:
        start(f"agent-{cfg}", [python_exe, "-u", "-m", "agent_runtime", "--config", cfg], LOGS_DIR / f"runner_{cfg}.log")
    if observer_cfg:
        start("observer", [python_exe, "-u", "-m", "observer", "--config", observer_cfg], LOGS_DIR / "observer.log")

    PID_FILE.write_text("\n".join(f"{pid} {label}" for label, pid in pids))
    print(f"\nStop with: python launch.py stop")


def stop_windows() -> None:
    if not PID_FILE.exists():
        print("No pid file found — nothing to stop.")
        return
    for line in PID_FILE.read_text().splitlines():
        parts = line.split(None, 1)
        if not parts:
            continue
        pid, label = parts[0], parts[1] if len(parts) > 1 else "?"
        result = subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"  Killed {label} (pid {pid})")
        else:
            print(f"  {label} (pid {pid}): {result.stderr.strip() or 'already gone'}")
    PID_FILE.unlink(missing_ok=True)


# ── tmux launcher ─────────────────────────────────────────────────────────────

def tmux(args: list[str]) -> None:
    subprocess.run(["tmux"] + args, check=True)


def session_exists() -> bool:
    result = subprocess.run(
        ["tmux", "has-session", "-t", SESSION],
        capture_output=True,
    )
    return result.returncode == 0


def launch_tmux(configs: list[str], observer_cfg: str | None = None) -> None:
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

    if observer_cfg:
        tmux(["split-window", "-h", "-t", f"{SESSION}:orch"])
        tmux(["send-keys", "-t", f"{SESSION}:orch", f"python -m observer --config {observer_cfg}", "Enter"])

    tmux(["select-layout", "-t", f"{SESSION}:orch", "even-horizontal"])
    tmux(["attach-session", "-t", SESSION])


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--observer", metavar="CONFIG", default=None)
    parser.add_argument("configs", nargs="*")
    known, _ = parser.parse_known_args()

    if known.configs == ["stop"]:
        if sys.platform == "win32":
            stop_windows()
        else:
            print("Use: tmux kill-session -t civ")
        return

    configs = known.configs or pick_configs()
    observer_cfg = known.observer or (pick_observer() if not known.configs else None)

    # Allow observer configs to be passed as positional args alongside runner configs
    if configs:
        obs_names = set(available_observer_configs())
        detected_observer = next((c for c in configs if c in obs_names), None)
        if detected_observer:
            configs = [c for c in configs if c != detected_observer]
            observer_cfg = observer_cfg or detected_observer

    if not configs:
        print("No configs selected.")
        sys.exit(1)

    unknown = [c for c in configs if c not in available_configs()]
    if unknown:
        print(f"Unknown configs: {', '.join(unknown)}")
        sys.exit(1)

    label = f"orchestrator + {configs}"
    if observer_cfg:
        label += f" + observer({observer_cfg})"
    print(f"Launching: {label}")

    if sys.platform == "win32":
        if PID_FILE.exists():
            print("Stopping previous session...")
            stop_windows()
        launch_windows(configs, observer_cfg)
    else:
        launch_tmux(configs, observer_cfg)


if __name__ == "__main__":
    main()
