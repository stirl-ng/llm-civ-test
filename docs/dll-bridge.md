# DLL ↔ Orchestrator Bridge

This document describes the DLL-side implementation of the LLM bridge.

See [protocol.md](protocol.md) for the full protocol specification.

## Overview

The DLL bridge enables Civ V to communicate with external LLMs:

1. **Detect LLM player's turn** → Send game state
2. **Receive action commands** → Execute in game
3. **Return results** → Include state changes
4. **Handle turn end** → Advance game

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Civ V Process                        │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │   Game Logic    │◄──►│          LLMBridge              │ │
│  │   (CvGame)      │    │  ┌─────────┐  ┌──────────────┐  │ │
│  │                 │    │  │ Message │  │ Named Pipe   │  │ │
│  │  - DoTurn       │    │  │ Queue   │  │ Server       │──┼─┼──► Orchestrator
│  │  - Units        │    │  └─────────┘  └──────────────┘  │ │
│  │  - Cities       │    │                                 │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Components

### LLMBridge Singleton

Manages all communication with the orchestrator.

```cpp
class LLMBridge {
public:
    static LLMBridge& Instance();

    void Initialize(const char* pipeName);
    void Shutdown();

    // Turn management
    void OnTurnStart(int playerId, const GameState& state);
    void OnTurnEnd();

    // Message handling
    void SendMessage(const json& msg);
    bool PollMessage(json& outMsg, int timeoutMs);

    // Action processing
    ActionResult ExecuteAction(const json& action);

private:
    NamedPipeServer m_pipe;
    ThreadSafeQueue<json> m_inbound;
    ThreadSafeQueue<json> m_outbound;
    std::thread m_workerThread;
};
```

### Message Flow

**Outbound (DLL → Orchestrator):**
1. Game calls `LLMBridge::SendMessage()`
2. Message queued to outbound buffer
3. Worker thread writes to pipe

**Inbound (Orchestrator → DLL):**
1. Worker thread reads from pipe
2. Message queued to inbound buffer
3. Game polls via `LLMBridge::PollMessage()`

## Protocol Messages

### Sending Turn Start

When it's the LLM player's turn:

```cpp
void CvGame::DoTurnForPlayer(int playerId) {
    if (IsLLMPlayer(playerId)) {
        json state = BuildGameState(playerId);
        json msg = {
            {"type", "turn_start"},
            {"player_id", playerId},
            {"turn", GetGameTurn()},
            {"state", state}
        };
        LLMBridge::Instance().SendMessage(msg);

        // Enter action loop
        ProcessLLMTurn(playerId);
    }
}
```

### Processing Actions

```cpp
void CvGame::ProcessLLMTurn(int playerId) {
    while (true) {
        json msg;
        if (!LLMBridge::Instance().PollMessage(msg, ACTION_TIMEOUT_MS)) {
            // Timeout - end turn
            break;
        }

        std::string type = msg["type"];

        if (type == "action") {
            ActionResult result = ExecuteAction(msg["action"]);
            json response = {
                {"type", "action_result"},
                {"request_id", msg["request_id"]},
                {"success", result.success},
                {"result", result.data},
                {"state_delta", result.delta}
            };
            LLMBridge::Instance().SendMessage(response);
        }
        else if (type == "get_state") {
            json state = BuildGameState(playerId);
            json response = {
                {"type", "state_refresh"},
                {"request_id", msg["request_id"]},
                {"state", state}
            };
            LLMBridge::Instance().SendMessage(response);
        }
        else if (type == "end_turn") {
            json ack = {{"type", "turn_end_ack"}, {"turn", GetGameTurn()}};
            LLMBridge::Instance().SendMessage(ack);
            break;
        }
    }
}
```

### Executing Actions

```cpp
ActionResult CvGame::ExecuteAction(const json& action) {
    std::string kind = action["kind"];
    ActionResult result;

    if (kind == "move_unit") {
        int unitId = action["unit_id"];
        int toX = action["to"][0];
        int toY = action["to"][1];

        CvUnit* unit = GetUnit(unitId);
        if (!unit) {
            result.success = false;
            result.data = {{"error", "UNIT_NOT_FOUND"}};
            return result;
        }

        bool moved = unit->MoveTo(toX, toY);
        result.success = moved;
        result.delta = {
            {"units", {{
                {"id", unitId},
                {"x", unit->getX()},
                {"y", unit->getY()},
                {"moves_remaining", unit->movesRemaining()}
            }}}
        };

        // Add revealed tiles to delta
        auto revealed = GetNewlyRevealedTiles(unit);
        if (!revealed.empty()) {
            result.delta["revealed_tiles"] = revealed;
        }
    }
    else if (kind == "attack") {
        // ... combat logic
    }
    else if (kind == "set_production") {
        // ... city production
    }
    // ... other action types

    return result;
}
```

## State Serialization

### Full Game State

```cpp
json CvGame::BuildGameState(int playerId) {
    CvPlayer* player = GetPlayer(playerId);

    return {
        {"turn", GetGameTurn()},
        {"era", GetEraName(player->GetCurrentEra())},
        {"gold", player->GetGold()},
        {"science_per_turn", player->GetSciencePerTurn()},
        {"culture_per_turn", player->GetCulturePerTurn()},
        {"faith", player->GetFaith()},
        {"happiness", player->GetHappiness()},
        {"cities", SerializeCities(player)},
        {"units", SerializeUnits(player)},
        {"technologies", SerializeTechTree(player)},
        {"diplomacy", SerializeDiplomacy(player)},
        {"resources", SerializeResources(player)},
        {"pending_decisions", SerializePendingDecisions(player)}
    };
}
```

### State Delta

Only include what changed:

```cpp
json CvGame::BuildStateDelta(const std::vector<Change>& changes) {
    json delta;

    for (const auto& change : changes) {
        switch (change.type) {
            case ChangeType::UnitMoved:
            case ChangeType::UnitDamaged:
                delta["units"].push_back(SerializeUnit(change.unitId));
                break;
            case ChangeType::UnitDestroyed:
                delta["units_removed"].push_back(change.unitId);
                break;
            case ChangeType::CityProductionChanged:
                delta["cities"].push_back(SerializeCity(change.cityId));
                break;
            case ChangeType::TileRevealed:
                delta["revealed_tiles"].push_back(SerializeTile(change.x, change.y));
                break;
            // ...
        }
    }

    return delta;
}
```

## Threading Model

- **Main game thread**: Calls `ProcessLLMTurn()`, executes actions
- **Pipe worker thread**: Reads/writes to named pipe
- **Thread-safe queues**: Buffer messages between threads

```
Main Thread                    Worker Thread
     │                              │
     │  SendMessage(msg)            │
     │ ───────────────────────►     │
     │                              │  [writes to pipe]
     │                              │
     │                              │  [reads from pipe]
     │  PollMessage()               │
     │ ◄───────────────────────     │
     │                              │
```

## Error Handling

### Pipe Disconnection

```cpp
void LLMBridge::OnPipeDisconnected() {
    // Log warning
    LogWarning("Orchestrator disconnected");

    // Clear queues
    m_inbound.clear();
    m_outbound.clear();

    // End current turn gracefully
    m_forceEndTurn = true;
}
```

### Invalid Actions

```cpp
ActionResult CvGame::ExecuteAction(const json& action) {
    try {
        // ... execute
    } catch (const std::exception& e) {
        return ActionResult{
            .success = false,
            .data = {{"error", e.what()}}
        };
    }
}
```

## Configuration

```cpp
// Default pipe name
#define LLM_PIPE_NAME "\\\\.\\pipe\\civv_llm"

// Timeouts
#define ACTION_TIMEOUT_MS 30000
#define PIPE_CONNECT_TIMEOUT_MS 5000

// Buffer sizes
#define PIPE_BUFFER_SIZE (64 * 1024)
#define MESSAGE_QUEUE_SIZE 100
```

## Integration Points

### CvGame Hooks

| Hook | Purpose |
|------|---------|
| `DoGameStarted` | Initialize bridge |
| `DoTurnForPlayer` | Trigger LLM turn |
| `OnShutdown` | Cleanup bridge |

### Required Includes

```cpp
#include "LLMBridge.h"
#include <nlohmann/json.hpp>  // or similar JSON library
```

## Testing

### Without Game

Use the orchestrator's `--stdio` mode:

```bash
echo '{"type":"turn_start","turn":1,"state":{}}' | python -m orchestrator --stdio --once
```

### Mock DLL

Python script to simulate DLL:

```python
# test_dll_mock.py
import json

# Simulate turn start
print(json.dumps({
    "type": "turn_start",
    "player_id": 0,
    "turn": 1,
    "state": {"gold": 100, "units": []}
}))

# Read actions until end_turn
while True:
    msg = json.loads(input())
    if msg["type"] == "end_turn":
        print(json.dumps({"type": "turn_end_ack", "turn": 1}))
        break
    elif msg["type"] == "action":
        print(json.dumps({
            "type": "action_result",
            "request_id": msg["request_id"],
            "success": True,
            "result": {},
            "state_delta": {}
        }))
```
