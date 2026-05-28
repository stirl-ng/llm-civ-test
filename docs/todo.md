# TODO

## DLL / C++

- **Strip `session_id` from C++ payloads** — Python no longer reads or uses `session_id`. It's emitted in every outgoing DLL message (turn_start, heartbeat, notifications, etc. in `CvGame.cpp`) and `GetSessionId()` in `GameStatePipe.cpp`. Remove the field from all `payload <<` lines and the `GetSessionId()` method.

- Include city growth stats (eg X turns until pop up/down) and more in get_cities and in brief

- **Track games_played per player** — removed from `PlayerProfile` (was never incremented). Re-add when there's a clear write path (e.g., detect new game in `runner.py` when `game_id` changes).

- handle actions for builders and settlers

- find way to communicate where to settle next (avoid borders and ocean)