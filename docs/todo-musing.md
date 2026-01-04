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


Game status pop up / notif (?)
    Eg, "The people that like to smile the most" or "the world's most well fed people" or "the people with the pointiest sticks"
    This triggers our pop up logger, but nothing else
    Need to know this info! Or it should be available in a tool call whenever?
    How is the game getting this? Is this available?


Quests
    These show up in our notification log
    Are they shown elsewhere too?
    Would be nice to have a better view/track of them
    + a tool call for the llm


New Era
    Other players are notified of us entering a new era, but not ourselves, ironically


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


Query for ids -> values
    Such as player_id, popup meanings, idk...
    tool call or do we keep a dict on our side?