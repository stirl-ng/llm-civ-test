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

## Journal TurnMemory needs replacement
`journal.py` stores `TurnMemory` objects with structured fields (summary, thoughts, mood, events). Replace with a simple recap list: `{turn: int, text: str}`. Written by LLM at reflection time, kept forever, queried in limited batches. See `docs/systems.md` Memory section for target model.

Related: `record_recap` and `update_strategy` tools don't exist yet. `get_recaps` doesn't exist yet. `get_lessons` exists but lessons aren't auto-injected into briefing.

---

## Tool schema bifurcation
`mcp_server._TOOLS` (orchestrator) and `schemas.py` (LLM-facing, OpenAI format) must be kept in sync manually. Adding a tool requires editing both. There is no generation or validation between them — drift is easy and silent.

---

## System prompt is monolithic
`system_prompt.py` generates one big string. No way to enable/disable sections, A/B test prompt strategies, or swap personality modules without editing the file. Needs a composition approach before serious prompt iteration begins.

Related: `generate_reflection_prompt()` in `briefing.py` references `update_knowledge_base` which does not exist. Fix before using that function.

---

## Cross-game learning loop not activated
The journal wires exist but the loop isn't closed:
- `record_lesson` is callable by the LLM but not mentioned in the system prompt
- `get_lessons` exists but cross-game lessons are not injected into the turn briefing
- Lesson review/revision cadence is not configured

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

## Per-tile yields missing from get_map_view
`get_visible_tiles` (C++) does not emit yield data per tile. `get_map_view` therefore cannot include `yields: {food, production, gold, ...}` in the `tiles` JSON it returns. To fix: extend the `get_visible_tiles` handler in `CvGame.cpp` to compute and emit yields for each plot (using `pPlot->calculateYield()` or similar), then surface them in the `tiles` array in `mcp_server._get_map_view`.
