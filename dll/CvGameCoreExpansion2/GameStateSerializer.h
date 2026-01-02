#pragma once

#include <string>

// Forward declarations for Civ V SDK types.
// When compiling with the real SDK, these are provided by SDK headers.
// When compiling standalone (CIVV_LLM_STANDALONE), we use mock data.

#ifndef CIVV_LLM_STANDALONE
// Real SDK mode - forward declare the types we need
class CvGame;
class CvPlayer;
class CvMap;
#endif

namespace GameStateSerializer {

// ============================================================================
// Game-Level Information Serialization
// ============================================================================
// Serializes the game-level state as defined in docs/game-state-info.md section 1.
// This includes:
//   - turn: Current turn number
//   - game_speed: Game speed type (QUICK, STANDARD, EPIC, MARATHON)
//   - difficulty: Difficulty level (SETTLER through DEITY)
//   - era: Current game era
//   - map_size: Map size setting
//   - map_type: Map type (PANGAEA, CONTINENTS, etc.)
//   - sea_level: Sea level setting
//   - players_alive: Number of active players
//   - civs_ever: Total civilizations that have existed
//   - victory_conditions: Available victory types
//   - victory_progress: Progress toward each victory condition
//
// Returns a JSON string in the format:
// {
//   "kind": "state",
//   "category": "game_level",
//   "data": { ... game level fields ... }
// }

#ifdef CIVV_LLM_STANDALONE
// Standalone mode: Generate mock data for testing
std::string serializeGameLevelInfo();
std::string serializeGameLevelInfoMock(int turn, const char* gameSpeed,
                                        const char* difficulty, const char* era);
#else
// Real SDK mode: Extract from actual game state
std::string serializeGameLevelInfo();
#endif

// ============================================================================
// Full State Snapshot
// ============================================================================
// Serializes a complete game state snapshot for the LLM.
// This wraps all individual serializers into a single JSON document.
// Designed to be called at the start of a player's turn.
//
// Returns a JSON string in the format:
// {
//   "kind": "state",
//   "data": {
//     "game": { ... },
//     "player": { ... },
//     "cities": [ ... ],
//     "units": [ ... ],
//     ...
//   }
// }

std::string serializeFullState();

// ============================================================================
// Victory Progress Helpers
// ============================================================================
// Helper functions for serializing victory condition progress

struct DominationProgress {
    int capitals_controlled;
    int capitals_needed;
};

struct ScienceProgress {
    int parts_built;
    int parts_needed;
    int techs_researched;
};

struct CultureProgress {
    int tourism;
    int tourism_per_turn;
    int influential_civs;
    int civs_needed;
};

struct DiplomaticProgress {
    int votes_controlled;
    int votes_needed;
    int city_state_allies;
    int turns_until_vote;
};

struct TimeProgress {
    int score;
    int rank;
    int turns_remaining;
};

struct VictoryProgress {
    bool domination_enabled;
    bool science_enabled;
    bool culture_enabled;
    bool diplomatic_enabled;
    bool time_enabled;

    DominationProgress domination;
    ScienceProgress science;
    CultureProgress culture;
    DiplomaticProgress diplomatic;
    TimeProgress time;
};

// ============================================================================
// Configuration
// ============================================================================

// Set the player ID to serialize state for (default: 0, the human player)
void setActivePlayer(int playerId);
int getActivePlayer();

// Enable/disable verbose logging during serialization
void setVerboseLogging(bool enabled);

} // namespace GameStateSerializer
