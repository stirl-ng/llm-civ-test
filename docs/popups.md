# Popup Handling Inventory

Popups that are not handled will block `end_turn`. Add entries as new popups are discovered.

Method column: **timer** = auto-close after N seconds | **state** = close when game state changes (choice was made)

| Popup | Lua File | Handled | Method | Notes |
|---|---|---|---|---|
| Dawn of Man (game start) | `LoadScreen.lua` | ✓ | timer | |
| Tech choice | `TechPopup.lua` | ✓ | state | Sends available techs to pipe |
| Production choice | `ProductionPopup.lua` | ✓ | state | Sends available items to pipe |
| Meet civilization intro | `LeaderHeadRoot.lua` | ✓ | timer | DEFAULT_ROOT popup type only |
| City-state diplomacy | `CityStateDiploPopup.lua` | ✓ | timer | |
| City-state greeting | `CityStateGreetingPopup.lua` | ✓ | timer | |
| Trade | `Includes/TradeLogic.lua` | ✓ | ? | Verify method |
| Goody hut reward | ? | ? | | Blocks end_turn; needs investigation |
| Natural wonder discovered | ? | ? | | Blocks end_turn; needs investigation |
| Policy adoption screen | ? | ? | | Blocks end_turn if open |
| Pantheon choice | ? | ? | | `select_pantheon` tool exists in orchestrator |
| Religion founding | ? | ? | | `found_religion` tool exists in orchestrator |
| Religion enhancement | ? | ? | | `enhance_religion` tool exists in orchestrator |

## Notes

- When a new popup is discovered blocking `end_turn`, find its Lua file in `(1) Community Patch/LUA/`, add auto-close logic, and update this table.
- Prefer timer-based close for informational popups. Use state-based close only when the popup requires a selection the LLM must make.
- Choice popups should send their options to the pipe before closing so the LLM can make an informed decision.
