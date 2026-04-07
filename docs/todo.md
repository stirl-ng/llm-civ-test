# TODO

## DLL / C++

- **Strip `session_id` from C++ payloads** — Python no longer reads or uses `session_id`. It's emitted in every outgoing DLL message (turn_start, heartbeat, notifications, etc. in `CvGame.cpp`) and `GetSessionId()` in `GameStatePipe.cpp`. Remove the field from all `payload <<` lines and the `GetSessionId()` method.

- Include city growth stats (eg X turns until pop up/down) and more in get_cities and in brief