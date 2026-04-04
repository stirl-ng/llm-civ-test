# Prompt Design Notes

Extracted and preserved from earlier design work. Use this when iterating on the system prompt and turn briefing. The specific tools and file references are outdated — the design principles are not.

---

## What the LLM Wants in the Turn Briefing

**Always present (low token cost, high value):**
- Current turn number
- Civ name and leader identity
- Brief status: cities, current research, gold, happiness
- Notifications since last turn (events that happened while other civs played)
- Pending decisions (tech choice, production needed, etc.)
- Last 2-3 turn recaps (what the LLM did recently)
- Current strategy (the LLM's stated goals for this game)
- Top N lessons (cross-game wisdom, most relevant recent ones)

**Available on demand via tools (do NOT dump in briefing):**
- Detailed unit positions and status
- City details (production, population, buildings)
- Full tech tree and research progress
- Diplomacy status
- Map information
- Victory progress breakdown
- Older recaps beyond the recent window (`get_recaps`)
- Full lesson list (`get_lessons`)

**What the LLM does NOT want:**
- Full game state dumps — too much cognitive load
- Every unit's position listed out
- Complete diplomatic history
- Raw JSON dumps without framing

---

## Turn Briefing Format Principle

Present state like RAM data — clear, structured, scannable. Not prose. Not a story. A concise header block followed by an invitation to act.

Rough structure:
```
TURN [N]

STATUS:
  Civ / Leader / Cities / Gold / Happiness / Research

RECENT EVENTS:
  (last 2-3 notable events with turn numbers)

PENDING:
  (decisions that need to be made this turn)

REMINDERS:
  (1-2 relevant lessons or strategic notes)

---
What will you do?
```

---

## Design Maxims

These should inform both system prompt content and briefing structure:

1. **Progressive Disclosure** — Start broad, drill down via tools when needed
2. **Explicit over implicit** — Tell the LLM what to do; don't assume it knows Civ conventions
3. **Feedback loops** — Every action should have clear, immediate feedback
4. **State caching** — Don't re-query unchanged data within a turn
5. **Error clarity** — Clear error messages, not cryptic failures
6. **Turn boundaries** — Make it unambiguous when a turn starts and ends
7. **Memory persistence** — Lessons and strategy survive across turns and games
8. **Tool simplicity** — One tool, one purpose

---

## What the LLM Should NOT Do (Warn Explicitly in System Prompt)

- Assume game state — query if unsure
- End turn without checking for pending decisions (tech, production)
- Ignore notifications and events
- Move units without a specific destination and reason
- Re-query the same state repeatedly within a turn
- Forget important events — record them as lessons

---

## Memory Model

Three types of persistent memory, each with a clear job:

| Type | Scope | Written | Auto-injected in briefing |
|------|-------|---------|--------------------------|
| **Recaps** | This game | LLM at reflection (end of turn) | Last N (configurable, default ~3) |
| **Strategy** | This game | LLM when plan changes | Always (single string) |
| **Lessons** | Cross-game | LLM proactively during play | Top N by recency (configurable) |

All are kept forever. Older recaps and full lesson lists are available via tools (`get_recaps`, `get_lessons`) when the LLM wants to look back further.

## Conversation History and Context Compression

- **Within a turn**: Full message history (tool calls, responses) is fine — turns are short
- **Across turns**: Nothing carries forward except what the briefing contains
- **Compression happens naturally**: Recaps replace raw history. Each turn, the LLM writes a 2-4 sentence recap. Next turn, that recap is in the briefing instead of all the tool calls.
- **Lesson review**: Every N turns (configurable), prompt the LLM to review and revise its lessons — prune stale ones, consolidate related ones. Not yet implemented.

---

## Notes on Differences from Claude Plays Pokemon

(Reference: `docs/claude_plays_pokemon_guide.md`)

- **No visual screenshots** — use structured state from DLL instead
- **Turn-based** — loop per turn, not per frame/action
- **Clear turn boundaries** — explicit start/end vs. continuous action stream
- **Different state** — cities/units/diplomacy vs. party/badges/map
- **Longer horizon** — 500 turns vs. one playthrough; compression matters more
