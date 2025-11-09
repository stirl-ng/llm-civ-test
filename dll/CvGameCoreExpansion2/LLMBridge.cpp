#include "LLMBridge.h"
#include "NamedPipeClient.h"
#include "Logger.h"

#include <windows.h>

namespace {
    NamedPipeClient* g_client = NULL;
    bool g_initialized = false;

    std::wstring get_pipe_name() {
        wchar_t buf[512];
        DWORD n = GetEnvironmentVariableW(L"CIVV_PIPE", buf, 512);
        if (n > 0 && n < 512) {
            return std::wstring(buf, buf + n);
        }
        return L"\\\\.\\pipe\\civv_llm";
    }

    void on_receive(const std::string& msg) {
        // For now we just log inbound messages. Integration points can hook here.
        logger::info(std::string("RX ") + msg);
        // TODO: validate against schemas/state.schema.json and actions.schema.json
        // TODO: dispatch actions to game systems
    }
}

namespace llmbridge {

bool initialize() {
    if (g_initialized) return true;
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

extern "C" __declspec(dllexport) bool LLMBridge_Initialize() { return initialize(); }
extern "C" __declspec(dllexport) void LLMBridge_Shutdown() { shutdown(); }
extern "C" __declspec(dllexport) bool LLMBridge_Send(const char* json_utf8) { return send_json(json_utf8); }
extern "C" __declspec(dllexport) bool LLMBridge_IsConnected() { return is_connected(); }

}
