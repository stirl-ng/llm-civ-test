#include "GameStateSerializer.h"
#include "JsonBuilder.h"
#include "Logger.h"

#include <cstring>

// When compiling with the real Civ V SDK, include the SDK headers here:
// #include "CvGameCoreDLL.h"
// #include "CvGame.h"
// #include "CvPlayer.h"
// #include "CvMap.h"
// #include "CvGlobals.h"

namespace {
    // Configuration state
    int g_activePlayer = 0;
    bool g_verboseLogging = false;

    // ========================================================================
    // String conversion helpers for game enums
    // ========================================================================

    // Game speed type to string
    const char* gameSpeedToString(int speedType) {
        // GameSpeedTypes enum values (from SDK):
        // 0 = GAMESPEED_QUICK, 1 = GAMESPEED_STANDARD, 2 = GAMESPEED_EPIC, 3 = GAMESPEED_MARATHON
        switch (speedType) {
            case 0: return "QUICK";
            case 1: return "STANDARD";
            case 2: return "EPIC";
            case 3: return "MARATHON";
            default: return "UNKNOWN";
        }
    }

    // Handicap (difficulty) type to string
    const char* handicapToString(int handicapType) {
        // HandicapTypes enum values:
        // 0 = SETTLER, 1 = CHIEFTAIN, 2 = WARLORD, 3 = PRINCE,
        // 4 = KING, 5 = EMPEROR, 6 = IMMORTAL, 7 = DEITY
        switch (handicapType) {
            case 0: return "SETTLER";
            case 1: return "CHIEFTAIN";
            case 2: return "WARLORD";
            case 3: return "PRINCE";
            case 4: return "KING";
            case 5: return "EMPEROR";
            case 6: return "IMMORTAL";
            case 7: return "DEITY";
            default: return "UNKNOWN";
        }
    }

    // Era type to string
    const char* eraToString(int eraType) {
        // EraTypes enum values:
        // 0 = ANCIENT, 1 = CLASSICAL, 2 = MEDIEVAL, 3 = RENAISSANCE,
        // 4 = INDUSTRIAL, 5 = MODERN, 6 = ATOMIC, 7 = INFORMATION
        switch (eraType) {
            case 0: return "ANCIENT";
            case 1: return "CLASSICAL";
            case 2: return "MEDIEVAL";
            case 3: return "RENAISSANCE";
            case 4: return "INDUSTRIAL";
            case 5: return "MODERN";
            case 6: return "ATOMIC";
            case 7: return "INFORMATION";
            default: return "UNKNOWN";
        }
    }

    // Map size type to string
    const char* mapSizeToString(int sizeType) {
        // WorldSizeTypes enum values:
        // 0 = DUEL, 1 = TINY, 2 = SMALL, 3 = STANDARD, 4 = LARGE, 5 = HUGE
        switch (sizeType) {
            case 0: return "DUEL";
            case 1: return "TINY";
            case 2: return "SMALL";
            case 3: return "STANDARD";
            case 4: return "LARGE";
            case 5: return "HUGE";
            default: return "UNKNOWN";
        }
    }

    // Sea level type to string
    const char* seaLevelToString(int seaLevel) {
        // SeaLevelTypes enum values:
        // 0 = LOW, 1 = MEDIUM, 2 = HIGH
        switch (seaLevel) {
            case 0: return "LOW";
            case 1: return "MEDIUM";
            case 2: return "HIGH";
            default: return "MEDIUM"; // Default
        }
    }

    // ========================================================================
    // Victory progress serialization helper
    // ========================================================================

    void serializeVictoryProgress(JsonBuilder& json, const GameStateSerializer::VictoryProgress& progress) {
        json.startObject("victory_progress");

        // Domination victory
        if (progress.domination_enabled) {
            json.startObject("domination");
            json.addInt("capitals_controlled", progress.domination.capitals_controlled);
            json.addInt("capitals_needed", progress.domination.capitals_needed);
            json.endObject();
        }

        // Science victory
        if (progress.science_enabled) {
            json.startObject("science");
            json.addInt("parts_built", progress.science.parts_built);
            json.addInt("parts_needed", progress.science.parts_needed);
            json.addInt("techs_researched", progress.science.techs_researched);
            json.endObject();
        }

        // Culture victory
        if (progress.culture_enabled) {
            json.startObject("culture");
            json.addInt("tourism", progress.culture.tourism);
            json.addInt("tourism_per_turn", progress.culture.tourism_per_turn);
            json.addInt("influential_civs", progress.culture.influential_civs);
            json.addInt("civs_needed", progress.culture.civs_needed);
            json.endObject();
        }

        // Diplomatic victory
        if (progress.diplomatic_enabled) {
            json.startObject("diplomatic");
            json.addInt("votes_controlled", progress.diplomatic.votes_controlled);
            json.addInt("votes_needed", progress.diplomatic.votes_needed);
            json.addInt("city_state_allies", progress.diplomatic.city_state_allies);
            json.addInt("turns_until_vote", progress.diplomatic.turns_until_vote);
            json.endObject();
        }

        // Time victory
        if (progress.time_enabled) {
            json.startObject("time");
            json.addInt("score", progress.time.score);
            json.addInt("rank", progress.time.rank);
            json.addInt("turns_remaining", progress.time.turns_remaining);
            json.endObject();
        }

        json.endObject(); // victory_progress
    }

    // ========================================================================
    // Victory conditions array helper
    // ========================================================================

    void serializeVictoryConditions(JsonBuilder& json, const GameStateSerializer::VictoryProgress& progress) {
        json.startArray("victory_conditions");
        if (progress.domination_enabled) json.addStringValue("DOMINATION");
        if (progress.science_enabled) json.addStringValue("SCIENCE");
        if (progress.culture_enabled) json.addStringValue("CULTURE");
        if (progress.diplomatic_enabled) json.addStringValue("DIPLOMATIC");
        if (progress.time_enabled) json.addStringValue("TIME");
        json.endArray();
    }

} // anonymous namespace

namespace GameStateSerializer {

// ============================================================================
// Configuration
// ============================================================================

void setActivePlayer(int playerId) {
    g_activePlayer = playerId;
}

int getActivePlayer() {
    return g_activePlayer;
}

void setVerboseLogging(bool enabled) {
    g_verboseLogging = enabled;
}

// ============================================================================
// Standalone/Mock Implementation
// ============================================================================

#ifdef CIVV_LLM_STANDALONE

std::string serializeGameLevelInfo() {
    // Return mock data for testing pipe infrastructure
    return serializeGameLevelInfoMock(42, "STANDARD", "PRINCE", "CLASSICAL");
}

std::string serializeGameLevelInfoMock(int turn, const char* gameSpeed,
                                        const char* difficulty, const char* era) {
    JsonBuilder json;

    json.startObject();
    json.addString("kind", "state");
    json.addString("category", "game_level");

    json.startObject("data");

    // Core game state
    json.addInt("turn", turn);
    json.addString("game_speed", gameSpeed);
    json.addString("difficulty", difficulty);
    json.addString("era", era);

    // Map settings (mock values)
    json.addString("map_size", "STANDARD");
    json.addString("map_type", "CONTINENTS");
    json.addString("sea_level", "MEDIUM");

    // Player counts (mock values)
    json.addInt("players_alive", 6);
    json.addInt("civs_ever", 8);

    // Victory conditions
    json.startArray("victory_conditions");
    json.addStringValue("DOMINATION");
    json.addStringValue("SCIENCE");
    json.addStringValue("CULTURE");
    json.addStringValue("DIPLOMATIC");
    json.addStringValue("TIME");
    json.endArray();

    // Victory progress (mock values)
    json.startObject("victory_progress");

    json.startObject("domination");
    json.addInt("capitals_controlled", 1);
    json.addInt("capitals_needed", 6);
    json.endObject();

    json.startObject("science");
    json.addInt("parts_built", 0);
    json.addInt("parts_needed", 6);
    json.addInt("techs_researched", 5);
    json.endObject();

    json.startObject("culture");
    json.addInt("tourism", 0);
    json.addInt("tourism_per_turn", 0);
    json.addInt("influential_civs", 0);
    json.addInt("civs_needed", 5);
    json.endObject();

    json.startObject("diplomatic");
    json.addInt("votes_controlled", 0);
    json.addInt("votes_needed", 0);
    json.addInt("city_state_allies", 0);
    json.addInt("turns_until_vote", 0);
    json.endObject();

    json.startObject("time");
    json.addInt("score", 245);
    json.addInt("rank", 3);
    json.addInt("turns_remaining", 458);
    json.endObject();

    json.endObject(); // victory_progress

    json.endObject(); // data
    json.endObject(); // root

    return json.str();
}

std::string serializeFullState() {
    // For now, just return game level info
    // This will be expanded to include all state categories
    return serializeGameLevelInfo();
}

#else

// ============================================================================
// Real SDK Implementation
// ============================================================================

std::string serializeGameLevelInfo() {
    // Real implementation using Civ V SDK
    // This code will compile when built with the full SDK
    //
    // Example usage pattern (pseudocode):
    //
    // CvGame& game = GC.getGame();
    // CvMap& map = GC.getMap();
    //
    // int turn = game.getGameTurn();
    // GameSpeedTypes speedType = game.getGameSpeedType();
    // HandicapTypes handicapType = game.getHandicapType();
    // EraTypes eraType = game.getCurrentEra();
    // WorldSizeTypes mapSize = map.getWorldSize();
    // int playersAlive = game.countCivPlayersAlive();
    //
    // bool dominationEnabled = game.isVictoryAvailable(VICTORY_DOMINATION);
    // etc.

    JsonBuilder json;

    json.startObject();
    json.addString("kind", "state");
    json.addString("category", "game_level");

    json.startObject("data");

    // TODO: Replace with actual SDK calls when integrated
    // For now, this will cause a linker error to remind us to integrate

    // CvGame& game = GC.getGame();
    // CvMap& map = GC.getMap();

    // Core game state
    // json.addInt("turn", game.getGameTurn());
    // json.addString("game_speed", game.getGameSpeedInfo().GetType());
    // json.addString("difficulty", game.getHandicapInfo().GetType());
    // json.addString("era", GC.getEraInfo(game.getCurrentEra())->GetType());

    // Placeholder until SDK is integrated
    json.addInt("turn", 0);
    json.addString("game_speed", "UNKNOWN");
    json.addString("difficulty", "UNKNOWN");
    json.addString("era", "UNKNOWN");
    json.addString("map_size", "UNKNOWN");
    json.addString("map_type", "UNKNOWN");
    json.addString("sea_level", "UNKNOWN");
    json.addInt("players_alive", 0);
    json.addInt("civs_ever", 0);

    json.startArray("victory_conditions");
    json.endArray();

    json.startObject("victory_progress");
    json.endObject();

    json.endObject(); // data
    json.endObject(); // root

    if (g_verboseLogging) {
        logger::info("Serialized game level info (placeholder - SDK not integrated)");
    }

    return json.str();
}

std::string serializeFullState() {
    // For now, just return game level info
    return serializeGameLevelInfo();
}

#endif // CIVV_LLM_STANDALONE

} // namespace GameStateSerializer
