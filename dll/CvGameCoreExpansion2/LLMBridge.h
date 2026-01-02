#pragma once

#include <string>

class NamedPipeClient;

namespace llmbridge {

bool initialize();
void shutdown();
bool send_json(const char* json_utf8);
bool is_connected();
bool receive_next(std::string& json_utf8);
void requeue(const std::string& json_utf8);

// Game state serialization and sending
// Serializes the current game state and sends it over the pipe.
// Returns true if the state was successfully serialized and queued for sending.
bool send_game_state();

// Serialize and send just the game-level information
// (turn, game speed, difficulty, era, map settings, victory conditions)
bool send_game_level_info();

// Exported C API
extern "C" __declspec(dllexport) bool LLMBridge_Initialize();
extern "C" __declspec(dllexport) void LLMBridge_Shutdown();
extern "C" __declspec(dllexport) bool LLMBridge_Send(const char* json_utf8);
extern "C" __declspec(dllexport) bool LLMBridge_IsConnected();

// Game state exports
extern "C" __declspec(dllexport) bool LLMBridge_SendGameState();
extern "C" __declspec(dllexport) bool LLMBridge_SendGameLevelInfo();

}
