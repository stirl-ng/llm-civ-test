# Civ V LLM Bridge

Let large language models play **Civilization V** autonomously. A custom DLL exports game state and accepts commands over a named pipe; a Python orchestrator bridges that to an HTTP API; an agent runner subscribes to turn events, calls the LLM, and executes tool calls until the turn ends.

## Architecture

```
Civ V DLL (C++) ──named pipe──► Orchestrator (Python) ──SSE/HTTP──► Agent Runner ──API──► LLM
```

**Turn flow:**
1. DLL sends `turn_start` over the pipe when it's the LLM player's turn
2. Orchestrator pushes the event to connected agent runners via SSE (`GET /events`)
3. Agent runner builds a briefing (current state + journal context) and calls the LLM
4. LLM queries state and issues actions via tool calls; runner executes each against the orchestrator
5. LLM calls `end_turn`; orchestrator forwards to DLL; game advances

The LLM maintains a persistent journal across turns and games: per-turn recaps, a current strategy, and cross-game lessons that feed back into future briefings.

## Quick Start

### 1. Build and install the DLL

The modified DLL lives in `CvGameCoreDLL_Expansion2/`. Build with Visual Studio and install it as a Civ V mod. See `docs/protocol.md` for what the DLL emits.

### 2. Start the orchestrator

```bash
cd python
pip install -r requirements.txt
python -m orchestrator
```

Waits for the DLL to connect, then starts the MCP HTTP server on `http://localhost:8765`.

### 3. Configure and run the agent

Copy the sample config and fill in your model:

```bash
cp python/configs/experiments/sample.yaml python/configs/experiments/myconfig.yaml
```

Set your API key as an environment variable (`OPENAI_API_KEY` or `GEMINI_API_KEY`) — never put keys in the config file. Then run the agent runner:

```bash
python -m agent_runtime --config openai
```

Or launch both orchestrator and runner together:

```bash
python launch.py openai          # Windows: logs to python/logs/
python launch.py openai          # Linux/Mac: opens a tmux session
python launch.py stop            # Windows: kill everything
```

### 4. Start a game

Launch Civ V with the mod active. Start a hotseat game with an LLM-controlled player. When it's their turn, the DLL connects and the agent takes over.

## Tools

The LLM has ~50 tools. Key ones:

| Category | Tools |
|----------|-------|
| State | `get_map_view`, `get_units`, `get_cities`, `get_available_techs`, `get_turn_blockers` |
| Units | `move_unit`, `unit_found_city`, `unit_skip`, `unit_sleep`, `unit_alert`, `unit_fortify` |
| City | `get_city_production`, `set_city_production` |
| Research | `choose_tech` |
| Memory | `record_recap`, `update_strategy`, `record_lesson`, `get_recaps`, `get_lessons` |
| Turn | `end_turn`, `force_end_turn` |

Full schema: `python/agent_runtime/tools/schemas.py`. Tool handlers: `python/orchestrator/mcp_server.py`.

## Project Structure

```
├── CvGameCoreDLL_Expansion2/  # Modified Civ V DLL (C++)
├── (1) Community Patch/LUA/   # Lua popup auto-handlers
├── python/
│   ├── orchestrator/          # Pipe client + HTTP/SSE server
│   ├── agent_runtime/         # LLM turn loop
│   │   ├── runner.py          # Entry point, SSE subscriber
│   │   ├── turn_runner.py     # Per-turn LLM loop
│   │   ├── briefing.py        # Turn briefing generator
│   │   ├── prompts/           # System prompt
│   │   ├── memory/            # Persistent journal (recaps, lessons, strategy)
│   │   ├── tools/             # Tool schemas + dispatch
│   │   └── models/            # LLM adapters (OpenAI, Gemini, Dummy)
│   ├── configs/experiments/   # YAML configs per model/experiment
│   ├── launch.py              # Launch orchestrator + runners
│   └── logs/                  # Runtime logs (per-process + per-game JSONL)
└── docs/                      # Architecture, protocol, state schema, issues
```

## Documentation

- [Architecture](docs/architecture.md) — Python component diagram
- [Orchestrator](docs/orchestrator.md) — CLI options and HTTP endpoints
- [Unit Actions](docs/unit-actions.md) — Unit action tools reference
- [Protocol](docs/protocol.md) — DLL ↔ Orchestrator pipe message format
- [State Schema](docs/state-schema.md) — Game state structure
- [Popup Handling](docs/popups.md) — Which popups are handled and how
- [Prompt Design](docs/prompt-design.md) — Briefing principles and design maxims
- [Systems](docs/systems.md) — Component status inventory
- [Issues](docs/issues.md) — Known gaps and active bugs
- [Model Welfare](MODEL_WELFARE.md) — Philosophy on LLM experience and agency
