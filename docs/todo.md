# TODO

## DLL / C++

- **Strip `session_id` from C++ payloads** — Python no longer reads or uses `session_id`. It's emitted in every outgoing DLL message (turn_start, heartbeat, notifications, etc. in `CvGame.cpp`) and `GetSessionId()` in `GameStatePipe.cpp`. Remove the field from all `payload <<` lines and the `GetSessionId()` method.

- Include city growth stats (eg X turns until pop up/down) and more in get_cities and in brief

- **Track games_played per player** — removed from `PlayerProfile` (was never incremented). Re-add when there's a clear write path (e.g., detect new game in `runner.py` when `game_id` changes).

- **Promotions not exposed** — `get_available_promotions` doesn't exist. Units that earn enough XP to promote can become `end_turn` blockers or get silently skipped. Need a tool + C++ pipe handler; turn loop should handle promotable units the way it handles blocking units.

- **Unhandled popups block end_turn** — Leaderboard popup and others in `docs/popups.md` have no Lua handler and will stall a run. Add Lua auto-close handlers for the remaining popups.

- handle actions for builders and settlers

- find way to communicate where to settle next (avoid borders and ocean)

- ensure x/y correctness on all maps