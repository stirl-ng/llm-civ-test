# Civ V LLM Hotseat Bridge

This project is a working concept for enabling large language models (LLMs) to play **Civilization V** in hotseat mode.  
It replaces the stock `CvGameCore_Expansion2.dll` with a custom build that exports the game state to an external process (Python) and executes inbound JSON actions.  

The result: automated Civ players driven by an LLM, fully deterministic and hotseat-safe, without relying on fragile UI automation.

---

## Features

- **Deterministic state export**: Cities, units, tech, known tiles, diplomacy.
- **Action intake**: JSON commands for research, policies, city queues, unit movement, and combat.
- **IPC transport**: Windows named pipe (`\\.\pipe\civv_llm`).
- **Safe execution**: All actions validated against the game’s legality checks before applying.
- **Hotseat compatible**: No FireTuner or cheat tools required.
- **Extensible**: Designed for incremental rollout of features (policies, workers, diplomacy, etc.).

---

## Architecture

```

\[ Civ V DLL ]  <--->  \[ Named Pipe ]  <--->  \[ Python Orchestrator ]  <--->  \[ LLM ]

````

- **Custom DLL (C++)**  
  - Hooks into `CvPlayer::doTurn()`.  
  - Exports compact game state as JSON.  
  - Applies validated JSON actions received via the pipe.  
- **Pipe Server (C++ in DLL)**  
  - Background thread manages IO.  
  - Main game thread drains inbound queue during turn execution.  
- **Python Orchestrator**  
  - Connects to `\\.\pipe\civv_llm`.  
  - Receives state snapshots.  
  - Prompts the LLM for next actions.  
  - Validates schema.  
  - Sends back JSON actions.

---

## Build Instructions (DLL)

1. Install **Civilization V SDK** from Steam.
2. Clone the official DLL source (BNW) or use the Community Patch Project (CPP) repo as reference.
3. Open the solution in **Visual Studio 2013** (or newer with v120 toolset).
4. Add [RapidJSON](https://github.com/Tencent/rapidjson) to the project (header-only).
5. Implement the pipe server (`CreateNamedPipe`, overlapped IO) and the turn hooks as described in `CvPlayer::doTurn()`.
6. Build in **Release** mode.
7. Package as a mod with the custom DLL (see Firaxis documentation on DLL mods).
8. Enable the mod in Civ V and start a hotseat game.

---

## Build Instructions (Python)

Requirements:
- Python 3.9+
- `pywin32` (for named pipe access)
- Any LLM client library (OpenAI, local model, etc.)

Example client:

```python
import json, win32file

pipe = r'\\.\pipe\civv_llm'
handle = win32file.CreateFile(pipe, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                              0, None, win32file.OPEN_EXISTING, 0, None)

def send(obj):
    win32file.WriteFile(handle, (json.dumps(obj) + "\n").encode("utf-8"))

def recv():
    _, data = win32file.ReadFile(handle, 4096)
    return json.loads(data.decode("utf-8").strip())

while True:
    msg = recv()
    if msg.get("kind") == "state":
        # Example: always pick Pottery
        send({"kind":"actions","data":{"research":"TECH_POTTERY"}})
````

---

## JSON Schemas

### State (outbound from DLL)

```json
{
  "kind": "state",
  "data": {
    "turn": 42,
    "gold": 123,
    "cities": [
      {"id": 1, "name": "Capital", "pop": 5, "build": "UNIT_SETTLER"}
    ],
    "units": [
      {"id": 10, "type": "UNIT_WARRIOR", "x": 5, "y": 6, "hp": 100, "moves": 2}
    ]
  }
}
```

### Actions (inbound to DLL)

```json
{
  "kind": "actions",
  "data": {
    "research": "TECH_POTTERY",
    "policy": "POLICY_TRADITION",
    "city_orders": [{"city_id": 1, "order": "UNIT_WORKER"}],
    "unit": [
      {"id": 10, "cmd": "MOVE", "to": [6, 6]},
      {"id": 10, "cmd": "ATTACK", "target_unit": 12}
    ]
  }
}
```

---

## Development Roadmap

1. **Bootstrap**

   * Build DLL and confirm it loads in game.
   * Pipe server accepts connections.
2. **Export**

   * Serialize turn + gold only.
   * Verify Python receives data.
3. **Actions**

   * Support setting research + city production.
   * Add basic unit moves.
4. **Expand**

   * Add combat, promotions, workers, diplomacy.
5. **Stress Test**

   * 2 LLM civs + 1 human in hotseat.
   * Run 100 turns without crash.
6. **Refinement**

   * Enforce JSON schema.
   * Add logging and fallback heuristics.
