# Plan: Config Completeness

## Overview

Several values important to experiment behavior are hardcoded in source rather than settable per
experiment via YAML config. This plan wires them in and fixes one broken stub.

---

## Findings

### Issue 1 — `temperature=0.2` hardcoded

- **Location**: `run.py:303` — `model.generate(messages, tools=tools, temperature=0.2)`
- `openai_adapter.py` already passes `**kwargs` through to the API call, so it supports temperature.
- Fix: add `agent.temperature` to YAML; thread through `main()` → `run_game_loop()` → `run_turn()` → `generate()`.

### Issue 2 — Personality not wired to config

- `run.py:264` calls `build_system_prompt(interactive=interactive)` — personality is always `None`.
- **Worse**: `build_system_prompt()` accepts a `personality` parameter but **never uses it in the
  body** — it's silently dropped even if passed. Double fix needed.
- 6 presets exist (`Scholar`, `Emperor`, `Survivor`, `Adventurer`, `Builder`, `Warlord`) in
  `personality.py`; none are selectable from config.
- Fix: (a) make `build_system_prompt()` actually inject `build_personality_prompt(personality)`;
  (b) add `agent.personality` to YAML; (c) thread `get_personality(name)` through to the call.

### Issue 3 — `generate_reflection_prompt` / `update_knowledge_base` (CLAUDE.md warning is wrong)

- The CLAUDE.md gotcha warning says this function references `update_knowledge_base` which doesn't exist.
- **Actual state**: `briefing.py` correctly references `record_recap`, `update_strategy`, and
  `record_lesson` — all valid tools handled in `run.py`. The function is fine.
- Fix: remove the stale warning from `CLAUDE.md`. No code change needed.

### Issue 4 — `poll_interval` (already in config, just undeclared)

- `run.py` already reads `cfg.get("orchestrator", {}).get("poll_interval", 2.0)` — not hardcoded.
- The YAML files just don't declare it, so the 2.0 default is silently applied.
- Fix: add `poll_interval: 2.0` with a deprecation comment to all three YAML configs.
  (Will be fully removed once SSE push work is done.)

---

## New YAML Structure

```yaml
agent:
  temperature: 0.2      # LLM sampling temperature (0.0–2.0)
  personality: scholar  # scholar | emperor | survivor | adventurer | builder | warlord
                        # omit or set to null for no personality

orchestrator:
  url: http://localhost:8765
  pipe: "\\.\pipe\civv_llm"
  poll_interval: 2.0    # DEPRECATED: unused once SSE push is in place
```

---

## Files to Change

| File | Change |
|---|---|
| `python/experiments/run.py` | Read `agent.temperature` + `agent.personality`; thread through |
| `python/agent_runtime/prompts/system_prompt.py` | Actually use the `personality` param (currently a no-op) |
| `python/configs/experiments/openai.yaml` | Add `agent:` section with temperature + personality |
| `python/configs/experiments/gemini.yaml` | Same |
| `python/configs/experiments/minimal.yaml` | Add explicit `poll_interval` with deprecation note |
| `CLAUDE.md` | Remove stale warning about `update_knowledge_base` in Gotchas section |

---

## Step-by-Step Changes

### `run.py`

In `main()`, after loading config:

```python
agent_cfg = config.get("agent", {})
temperature = agent_cfg.get("temperature", 0.7)
personality_name = agent_cfg.get("personality")
personality = get_personality(personality_name) if personality_name else None
```

Add import: `from agent_runtime.prompts.personality import get_personality`

Thread `temperature` and `personality` into `run_game_loop()`:

```python
run_game_loop(
    model, base_url,
    temperature=temperature,
    personality=personality,
    ...
)
```

`run_game_loop()` signature: add `temperature: float = 0.7, personality=None`.
Pass both to `run_turn()`.

`run_turn()` signature: add `temperature: float = 0.7, personality=None`.

In `run_turn()`, change the generate call:
```python
# was: model.generate(messages, tools=tools, temperature=0.2)
response = model.generate(messages, tools=tools, temperature=temperature)
```

In `run_turn()`, change the system prompt call:
```python
# was: build_system_prompt(interactive=interactive)
system_content = build_system_prompt(personality=personality, interactive=interactive)
```

### `system_prompt.py`

Find `build_system_prompt(personality=None, interactive=False)`. Locate where the prompt string
is assembled and add the personality block when provided:

```python
if personality:
    from .personality import build_personality_prompt
    prompt += "\n\n" + build_personality_prompt(personality)
```

(Exact insertion point depends on the current structure — place it before the closing
"tool guidance" section so it reads as character before mechanics.)

### Config YAMLs

**`openai.yaml`** — add:
```yaml
agent:
  temperature: 0.7
  personality: scholar
```

**`gemini.yaml`** — add:
```yaml
agent:
  temperature: 0.7
  personality: scholar
```

**`minimal.yaml`** — add to `orchestrator:` section:
```yaml
orchestrator:
  ...
  poll_interval: 2.0  # DEPRECATED: will be removed with SSE push implementation
```

### `CLAUDE.md`

In the Gotchas section, remove:

> `generate_reflection_prompt()` in `briefing.py` references `update_knowledge_base` which does not exist — stale, needs fixing before use.

Replace with nothing (or optionally note that it was verified working as of this change).

---

## Verification

1. Run `python experiments/run.py openai` — confirm personality voice appears in the LLM's
   responses (check logs for system prompt containing personality content)
2. Change `temperature: 0.0` in config, run a turn — responses should be deterministic/repetitive
3. Run `python experiments/run.py minimal` — smoke test still passes with dummy model
4. Grep for `temperature=0.2` in codebase — should return no results
