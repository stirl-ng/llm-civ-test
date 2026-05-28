# Popup Handling Inventory

## Popups vs. Notifications

These are two separate mechanisms that often fire together:

**Popups** (`BUTTONPOPUP_*`) — Civ V UI layer. Queued in `UIManager`. While a popup is in the queue (even unshown), `canEndTurn()` can return false, blocking `end_turn`. Handled in Lua; the LLM never sees them directly.

**Notifications** (`type: notification`) — DLL pipe events. Sent via `GameStatePipe` → orchestrator → message logger. Accessible to the LLM via `get_notifications`. These fire independently of popups and are not the same thing.

Example — meeting a city-state fires **both**: a `BUTTONPOPUP_CITY_STATE_GREETING` popup (which we immediately dismiss in Lua) **and** a `"You have met the City-State of X"` notification over the pipe (which lands in the log and the LLM can read).

The LLM learns about game events via notifications, not popups. The job of the Lua popup handlers is purely to prevent the UI queue from stalling `end_turn`.

---

## Popup Blocking Reference

Method column: **instant** = `PopupProcessed` fired immediately in `OnPopup`, popup never queued | **timer** = auto-close after N seconds | **state** = close when game state changes (choice made via tool)

| Popup | Lua File | Handled | Method | Notes |
|---|---|---|---|---|
| Dawn of Man (game start) | `LoadScreen.lua` | ✓ | timer | |
| Tech choice | `TechPopup.lua` | ✓ | state | Sends available techs to pipe before closing |
| Production choice | `ProductionPopup.lua` | ✓ | state | Sends available items to pipe before closing |
| Meet civilization intro | `LeaderHeadRoot.lua` | ✓ | timer | DEFAULT_ROOT popup type only |
| City-state greeting | `CityStateGreetingPopup.lua` | ✓ | instant | Informational only; notification fires separately over pipe |
| City-state diplomacy | `CityStateDiploPopup.lua` | ✓ | timer | Has action buttons; LLM interacts via tools not this popup |
| Trade | `Includes/TradeLogic.lua` | ✓ | ? | Verify method |
| Goody hut reward (informational) | `GoodyHutPopup.lua` | ✓ | timer | `BUTTONPOPUP_GOODY_HUT_REWARD` |
| Goody hut choice (picker promotion) | `ChooseGoodyHutReward.lua` | ✓ | timer | Auto-selects first valid option; only shown when unit has `PROMOTION_GOODY_HUT_PICKER` |
| Great Work completed | `GreatWorkPopup.lua` | ✓ | instant | `BUTTONPOPUP_GREAT_WORK_COMPLETED_ACTIVE_PLAYER`; informational only |
| Natural wonder discovered | ? | ? | | Blocks end_turn; needs investigation |
| Policy adoption screen | ? | ? | | Blocks end_turn if open |
| Pantheon choice | ? | ? | | `select_pantheon` tool exists in orchestrator |
| Religion founding | ? | ? | | `found_religion` tool exists in orchestrator |
| Religion enhancement | ? | ? | | `enhance_religion` tool exists in orchestrator |

---

## Fixing a Blocking Popup

1. Note the popup title (visible on screen) or the `BUTTONPOPUP_*` type from the log.
2. Look up the type in `LuaCATS/enum/ButtonPopupTypes.d.lua` to get the numeric ID.
3. Search `CvMinorCivAI.cpp` / `CvPlayer.cpp` / `CvGame.cpp` for `AddPopup` calls with that type to understand when it fires and whether a parallel `AddNotification` also fires.
4. Find the Lua handler in `(1) Community Patch/LUA/` or `Core Files/Overrides/`. If none, check the base game at `Assets/DLC/Expansion2/UI/InGame/Popups/`.
5. Choose a method:
   - **Informational popup** (no player choice required): use **instant** — fire `Events.SerialEventGameMessagePopupProcessed.CallImmediate(type, 0)` at the top of `OnPopup` and return. Never call `UIManager:QueuePopup`.
   - **Choice popup** (LLM must select): send options to pipe first, use **state** — close when the choice arrives as a pipe command.
   - **Timer** is a fallback when neither applies cleanly.
6. If the file is in `LUA/`, it's already loaded. If creating a new override in `Core Files/Overrides/`, add an `import="1"` entry to the `.modinfo` (with md5 from `md5sum`) and copy to the installed MODS directory.
7. Update this table.

## Notes

- **Prefer instant over timer for informational popups.** Timer depends on `UIManager:QueuePopup` being reached and the popup reaching the front of the queue. Instant fires `PopupProcessed` before the popup enters the queue, so it can never stall.
- Choice popups should send their options to the pipe before closing so the LLM can make an informed decision.
- The base game uses `UI.incTurnTimerSemaphore()` / `UI.decTurnTimerSemaphore()` to block end-turn while a popup is shown. Our handlers omit this semaphore for informational popups. For instant-method popups, even the queue entry is skipped, so there is no blocking at all.
