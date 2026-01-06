On Tech Unlocks:
    Modal shows:
        - Leads To
        - Units Unlocked
        - Wonders Unlocked
        - Builds Unlocked
        - Buildings Unlocked
        - Unique Actions (?)
        - Resources Unlocked

    These would be good for models to know... 
    Is this exposed elsewhere?

    1. Do they know what tech tree looks like ahead of time? (they should)
    2. Do they know what units they can and have unlocked?
    3. Do they know what wonders they can and have unlocked?
    4. Same for other science/work/building/units/etc

    There is also the cute little quote for each unlock. I think that should be included just for fun :)


Missing "Ruins Explored" modal info
    Need to know what getting the ruin got us
    also confirmation that we got the ruin


Policy screen...
    This may be a big push. 
    Or perhaps it's just visually complex but we can tell LLMs the unlock tree and what they can do and it's simple


✓ Game status pop up / notif (?)
    Eg, "The people that like to smile the most" or "the world's most well fed people" or "the people with the pointiest sticks"
    This triggers our pop up logger, but nothing else
    Need to know this info! Or it should be available in a tool call whenever?
    How is the game getting this? Is this available?
    ✓ DONE: get_demographics returns rankings with best/worst/average for all stats


Quests
    These show up in our notification log
    Are they shown elsewhere too?
    Would be nice to have a better view/track of them
    + a tool call for the llm


New Era
    Other players are notified of us entering a new era, but not ourselves, ironically


Great Work Completed
    Same as above, others see ours, but we don't see our own


Trade / Diplo
    Doesn't show exact trade
        📥 Incoming from DLL: { "type": "diplomatic_message", "player": 2, "diplo_ui_state": 4, "animation": 9, "turn": 95, "message": "You have a Luxury Resource that my people want. On their behalf, let's trade, shall we?" } 
    Need more info...


Influence Decay Notifs
    These appear to show up visually one turn later than they do in the log? Weird... I suppose not an issue though?


City Management Screen
    This never is shown to the player unless they click on cities
    Needs to be exposed in tool call
    Lets you, eg:
        - Buy tiles
        - ???
    Change production, view all productions, timelines...


Query for ids -> values
    Such as player_id, popup meanings, idk...
    tool call or do we keep a dict on our side?


Player UI sees:
    Info Panel (options)
        Research Info
        Unit List
        City List
        Resource List
        Great Person List
        (add more of our own?)

    ✓ Top Info Bar (+hover info)
        Science per turn                ->  Tech Tree (what does this look like in data? jsonify? keep visual+era info?)
        ✓ Gold per turn                 ->  economic overview (DONE: get_economic_overview)
        Trade units / trade routs       ->  trade route overview
        Happiness                       ->  None
        Golden Age status               ->  None
        Culture / Policy                ->  Social Policies / Ideological Tenets
        Tourism                         ->  Culture Overview
        Faith                           ->  Religion Overview
        Turn + Year                     ->  None
        Help                            ->  Could be cool to implement for docs for AI?
        Menu                            ->  Do we bother?

    Additional Information
        Advisor Counsel
        ✓ Demographics
        Diplomacy Overview
        ✓ Economic Overview
        Espionage Overview
        Military Overview
        ✓ Notification Log
        Religion Overview
        Tech Tree
        Trade Route Overview
        Victory Progress
        World Congress

 
Important Adds
    "needs orders" list
        mentioned in discussion of auto-missions (a queued, multi-turn) 
            do we need this too?

MPSIMULTANEOUS_TURNS
    We have sequential mode... thought?
    TODO later...


Enemy Civ Info?
    Units
        We have a unit list ourselves, but we can't use get_units on enemies because it will return info we shouldn't have, yes?
        Hmmm...
    City info...
    Abide fog of war...
    Etc...



---

## Research Findings (Claude Code Investigation)

### Tech Tree - How to Access

**Use the game DATABASE, not raw XML files.**

- Mods modify the database at load time, not just XML
- `GameInfo.Technologies` in Lua gives access to all techs (mod-aware)
- `GameInfo.Technology_PrereqTechs` gives prerequisite relationships
- DLL has `CvTechEntry` class via `GC.getTechInfo(eTech)`

Available fields per tech:
- `Type`, `Description`, `Quote` (the fun quote!)
- `GridX`, `GridY` (tree position for visual layout)
- `Era`, `ResearchCost`
- `PrereqOrTechs`, `PrereqAndTechs`

Unlocks via related tables:
```lua
-- Units unlocked by tech
DB.CreateQuery("SELECT * FROM Units WHERE PrereqTech = ?")("TECH_MINING")
-- Buildings, Builds, etc. same pattern
```

### Ruins / Goody Huts

- `GameInfo.GoodyHuts` has goody definitions in database
- `CvGoodyHuts` class tracks recent goodies per player (prevents repeats)
- When popped: `GAMEEVENT_GoodyHutReceivedBonus(iPlayer, iUnit, eGoody, iX, iY)`
- `NOTIFICATION_GOODY` is sent but doesn't include WHAT was received
- **FIX NEEDED**: Hook into `CvPlayer::receiveGoody()` or the Lua event to capture the actual reward

### Policy Tree

- Same pattern as tech tree!
- `GameInfo.Policies` and `GameInfo.PolicyBranchTypes` in Lua
- `CvPolicyEntry` class in DLL with `GridX`, `GridY` for tree layout
- Populated from `CIV5PolicyInfos.xml` (+ mod changes via database)
- `CvPlayerPolicies` tracks which policies a player has

### Quests (City-State)

- `CvMinorCivQuest` class stores quest data per player
- Quest types defined in `MinorCivQuestTypes` enum (35+ types!)
- Lua access: `Player:GetActiveQuestForPlayer()` (deprecated but works)
- Better: `MinorCivAI:GetActiveQuestTypes()` returns list of active quests
- Quest data includes: type, start turn, end turn, primary/secondary/tertiary data, rewards

### ✓ Game Status / Demographics / Rankings

- NOT stored in database - calculated at runtime
- Lua functions available:
  - `Player:GetScore()`, `GetScoreFromCities()`, `GetScoreFromPopulation()`, etc.
  - `Team:GetScore()`
  - `Game:GetPlayerScore()`
- "Pointiest sticks" rankings calculated by comparing all players
- ✓ IMPLEMENTED: `get_demographics` tool call returns all stats + rankings for all players

### ✓ Notification Log

- **NOT in the database** - stored in-memory only
- `CvNotifications` class holds up to 150 notifications per player
- Struct per notification: `m_eNotificationType`, `m_strMessage`, `m_strSummary`, `m_iX`, `m_iY`, `m_iTurn`, etc.
- Lua access: `Player:GetNotifications():GetNumNotifications()`, `GetNotificationStr(i)`, etc.
- Our pipe already captures notifications as they're created (good!)
- ✓ IMPLEMENTED: `get_notifications` tool call returns all notifications (up to 150) for a player

### New Era

- `BUTTONPOPUP_NEW_ERA` popup for the player entering the era
- `NOTIFICATION_OTHER_PLAYER_NEW_ERA` sent to OTHER players
- Self-notification gap exists (ironic) - popup handles it for human
- **FIX**: Send pipe message when player enters new era (in `CvTeam::SetCurrentEra`)

### Trade / Diplo Details

- Deals stored in `CvDeal` class with `m_TradedItems` vector
- Each `CvTradedItem` has: `m_eItemType`, `m_iData1/2/3`, `m_eFromPlayer`, `m_iDuration`, etc.
- `TradeableItems` enum defines 16+ item types (gold, resources, cities, techs, etc.)
- Our `SendDiplomaticMessageToPipe` already serializes deal items when present
- The "You have a Luxury Resource..." message is the AI's opening - actual trade details come in `deal` field if deal is attached

### ID Lookups

Most IDs map to database tables:
- `NotificationTypes` -> hardcoded enum, but `GameInfo.Notifications` has some
- `PlayerTypes` -> just 0-N indices, get names via `Player:GetName()`
- `PopupTypes` -> `BUTTONPOPUP_*` enums, can expose mapping
- Recommend: build a static lookup dict on Python side from database queries at game start

