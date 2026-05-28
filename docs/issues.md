# Active Issues

These are known problems and pending work. Not a graveyard — remove entries when resolved.

---

## Multi-agent not yet supported
The orchestrator has a single `GameState` object with no concept of multiple simultaneous runners. To support multiple agents (one per civ):
- Orchestrator needs per-player event routing
- SSE streams need `player_id` filtering
- Runners must register their `player_id` on connect
- Hotseat (sequential) works structurally once SSE is in place; simultaneous multiplayer requires concurrent routing and live fog-of-war event forwarding between players

---

## Tool schema bifurcation
`mcp_server._TOOLS` (orchestrator) and `schemas.py` (LLM-facing, OpenAI format) must be kept in sync manually. Adding a tool requires editing both. There is no generation or validation between them — drift is easy and silent.

---

## System prompt is monolithic
`system_prompt.py` generates one big string. No way to enable/disable sections, A/B test prompt strategies, or swap personality modules without editing the file. Needs a composition approach before serious prompt iteration begins.

---

## Cross-game lesson review not implemented
The lesson write/read loop is working: `record_lesson` is in the system prompt, and lessons are auto-injected into the turn briefing via `build_context_summary`. What's missing: periodic lesson review. Every N turns, prompt the LLM to review its lessons — prune stale ones, consolidate related ones. Cadence is configurable in design but not wired up.

---

## Interactive mode blocks unsupervised runs
`prompt_operator()` in `run.py` blocks on stdin. Configs must explicitly set `interactive: false` for unsupervised runs. The function should be removed or replaced with a non-blocking mechanism (e.g., a queue checked from outside the loop).

---

## Multi-model config has no convention
Model name normalization for journal scoping (e.g., `openai:gpt-4o` → `openai_gpt-4o`) is implicit in `journal.py::set_current_player()`. No documented rules for adding a new model backend or ensuring its player_id is stable across config changes.

---

## session_id leaks into game-layer messages
`session_id` is a pipe-connection counter useful only for request routing. C++ includes it in every outgoing message. The orchestrator injects it into tool requests. It adds noise and is a refactor candidate — the game layer should only care about `game_id`.

---

## Unhandled popups
Some popups still block `end_turn`. See `docs/popups.md` for current status.

Known outstanding: intermittent leaderboard popups still block (not in the popups inventory yet).

## Human-gated popups need a systematic fix

Several popups only appear for `isHuman()` players — the C++ check gates them. Because the LLM player is registered as human, it receives these popups, which block `end_turn` until a choice is made. Current workarounds use Lua timer overrides that auto-pick (e.g. `ChooseGoodyHutReward.lua` auto-selects the first valid option). These are stopgaps.

The right fix is one of:
- **C++ gate**: Add an `ISHUMAN_LLM` flag (or check a per-player "auto-resolve" bit) so the C++ skips the popup and picks randomly for LLM players — no Lua needed.
- **LLM tool**: For choices that are strategically significant, send options over the pipe and add a tool (like TechPopup/ProductionPopup) so the LLM actually decides.

Other popups likely affected by the same pattern: any VP/CBP feature that adds a `BUTTONPOPUP_CHOOSE_*` guarded by `isHuman()`. Audit `CvPlayer.cpp` and `CvGame.cpp` for all `AddPopup` calls inside `isHuman()` branches before fixing individually.

---

## Notification timing / missed events
Notifications sometimes appear at the end of the turn that generated them but are only visible at the start of the next. A worker being killed may go unacknowledged because the LLM only sees the notification one turn late. Need a better notification delivery model — options include buffering pending notifications into the next turn's briefing explicitly, or including prior-turn notifications in the briefing with a "from last turn" label.

---

## LLM unaware of new tools
After adding new tools, the system prompt and briefing do not automatically reflect them. The LLM has to either be told explicitly or call `get_tools`. Need a pattern for keeping the system prompt's tool section current without manual drift.

---

## Promotions not exposed
`get_available_promotions` and other promotion-related tools do not exist. Units that have enough XP to promote are likely blocking end_turn or being silently ignored.

---

## Long-game context compression not implemented
See `docs/prompt-design.md`. For games > ~50 turns, accumulated context will overflow. Progressive summarization (every N turns, summarize + clear history) is designed but not implemented.

---

## unit-actions.md response schema unverified
`docs/unit-actions.md` documents that action responses include a `state_delta` field. This has not been verified against live DLL output — the DLL may not emit deltas at all. Verify before relying on it.

---

## x/y coordinate correctness unverified across map types
Tile coordinates passed to and from tools (e.g. `move_unit`, `get_map_view`) have not been verified to be consistent across all map types and sizes. A mismatch between Lua, C++, and Python coordinate conventions could cause units to move to wrong tiles or tool calls to fail silently. Needs a deliberate test across at least two map sizes before coordinate-sensitive features are trusted.

---

## AI popup behavior vs LLM popup behavior
Open question: do C++ AI players ever receive popups that block their turn, or does the C++ always resolve AI decisions inline without showing a popup? If AI players are fully popup-free, then every `isHuman()`-gated popup we encounter is LLM-specific — which informs the fix strategy (see **Human-gated popups** above). Verify by checking `CvPlayer.cpp` and `CvGame.cpp` for any `AddPopup` calls NOT inside an `isHuman()` branch.

---

## Per-tile yields missing from get_map_view
`get_visible_tiles` (C++) does not emit yield data per tile. `get_map_view` therefore cannot include `yields: {food, production, gold, ...}` in the `tiles` JSON it returns. To fix: extend the `get_visible_tiles` handler in `CvGame.cpp` to compute and emit yields for each plot (using `pPlot->calculateYield()` or similar), then surface them in the `tiles` array in `mcp_server._get_map_view`.
