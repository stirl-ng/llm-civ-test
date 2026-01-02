#include "LLMBridge.h"
#include "NamedPipeClient.h"
#include "Logger.h"
#include "GameStateSerializer.h"

#include <windows.h>
#include <queue>

namespace {
    NamedPipeClient* g_client = NULL;
    bool g_initialized = false;
    bool g_queue_initialized = false;
    CRITICAL_SECTION g_queue_cs;
    std::queue<std::string> g_inbound;

    std::wstring get_pipe_name() {
        wchar_t buf[512];
        DWORD n = GetEnvironmentVariableW(L"CIVV_PIPE", buf, 512);
        if (n > 0 && n < 512) {
            return std::wstring(buf, buf + n);
        }
        return L"\\\\.\\pipe\\civv_llm";
    }

    void ensure_queue() {
        if (!g_queue_initialized) {
            InitializeCriticalSection(&g_queue_cs);
            g_queue_initialized = true;
        }
    }

    void destroy_queue() {
        if (!g_queue_initialized) return;
        DeleteCriticalSection(&g_queue_cs);
        while (!g_inbound.empty()) {
            g_inbound.pop();
        }
        g_queue_initialized = false;
    }

    void on_receive(const std::string& msg) {
        ensure_queue();
        logger::info(std::string("RX ") + msg);
        EnterCriticalSection(&g_queue_cs);
        g_inbound.push(msg);
        LeaveCriticalSection(&g_queue_cs);
    }
}

namespace llmbridge {

bool initialize() {
    if (g_initialized) return true;
    ensure_queue();
    logger::init();
    logger::info(L"LLMBridge initializing");
    if (g_client == NULL) {
        g_client = new NamedPipeClient();
    }
    if (g_client == NULL) {
        logger::error("Failed to allocate NamedPipeClient");
        logger::shutdown();
        return false;
    }
    if (!g_client->start(get_pipe_name(), &on_receive)) {
        logger::error("Failed to start NamedPipeClient");
        delete g_client;
        g_client = NULL;
        logger::shutdown();
        return false;
    }
    g_initialized = true;
    return true;
}

void shutdown() {
    if (!g_initialized) return;
    g_initialized = false;
    logger::info(L"LLMBridge shutting down");
    if (g_client) {
        g_client->stop();
        delete g_client;
        g_client = NULL;
    }
    destroy_queue();
    logger::shutdown();
}

bool send_json(const char* json_utf8) {
    if (!g_initialized || !g_client) return false;
    if (!json_utf8) return false;
    std::string s(json_utf8);
    // Minimal guard for JSON format. Full schema validation pending.
    if (s.empty() || s.size() > (1u << 20)) return false;
    const char first = s[0];
    const char last = s[s.size() - 1];
    if (!((first == '{' && last == '}') || (first == '[' && last == ']'))) return false;
    return g_client->send(s);
}

bool is_connected() {
    return g_client && g_client->is_connected();
}

bool receive_next(std::string& json_utf8) {
    if (!g_queue_initialized) return false;
    EnterCriticalSection(&g_queue_cs);
    if (g_inbound.empty()) {
        LeaveCriticalSection(&g_queue_cs);
        return false;
    }
    json_utf8 = g_inbound.front();
    g_inbound.pop();
    LeaveCriticalSection(&g_queue_cs);
    return true;
}

void requeue(const std::string& json_utf8) {
    ensure_queue();
    EnterCriticalSection(&g_queue_cs);
    g_inbound.push(json_utf8);
    LeaveCriticalSection(&g_queue_cs);
}

bool send_game_state() {
    if (!g_initialized) {
        logger::error("send_game_state: not initialized");
        return false;
    }
    std::string json = GameStateSerializer::serializeFullState();
    if (json.empty()) {
        logger::error("send_game_state: serialization returned empty");
        return false;
    }
    logger::info("Sending game state (" + std::to_string(json.size()) + " bytes)");
    return send_json(json.c_str());
}

bool send_game_level_info() {
    if (!g_initialized) {
        logger::error("send_game_level_info: not initialized");
        return false;
    }
    std::string json = GameStateSerializer::serializeGameLevelInfo();
    if (json.empty()) {
        logger::error("send_game_level_info: serialization returned empty");
        return false;
    }
    logger::info("Sending game level info (" + std::to_string(json.size()) + " bytes)");
    return send_json(json.c_str());
}

extern "C" __declspec(dllexport) bool LLMBridge_Initialize() { return initialize(); }
extern "C" __declspec(dllexport) void LLMBridge_Shutdown() { shutdown(); }
extern "C" __declspec(dllexport) bool LLMBridge_Send(const char* json_utf8) { return send_json(json_utf8); }
extern "C" __declspec(dllexport) bool LLMBridge_IsConnected() { return is_connected(); }
extern "C" __declspec(dllexport) bool LLMBridge_SendGameState() { return send_game_state(); }
extern "C" __declspec(dllexport) bool LLMBridge_SendGameLevelInfo() { return send_game_level_info(); }

}
