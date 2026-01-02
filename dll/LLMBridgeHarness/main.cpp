#include <windows.h>
#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <vector>

#include "../CvGameCoreExpansion2/LLMBridge.h"
#include "../CvGameCoreExpansion2/GameStateSerializer.h"

static void usage() {
    std::wcout << L"LLMBridgeHarness\n"
               << L"Usage: LLMBridgeHarness.exe [options]\n"
               << L"Options:\n"
               << L"  --pipe <name>  Pipe name (default: \\\\.\\pipe\\civv_llm)\n"
               << L"  --json <json>  Send custom JSON message\n"
               << L"  --state        Send mock game state (game-level info)\n"
               << L"  --server       Run a simple named-pipe server (echo)\n"
               << L"  --once         Server handles a single client then exits\n"
               << L"  --help         Show this help message\n";
}

static int run_server(const std::wstring& pipe_name, bool once) {
    std::wcout << L"[server] Creating pipe: " << pipe_name << std::endl;

    while (true) {
        HANDLE pipe = CreateNamedPipeW(
            pipe_name.c_str(),
            PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
            1,
            64 * 1024,
            64 * 1024,
            0,
            nullptr);

        if (pipe == INVALID_HANDLE_VALUE) {
            std::wcerr << L"[server] CreateNamedPipeW failed: " << GetLastError() << std::endl;
            return 2;
        }

        std::wcout << L"[server] Waiting for client..." << std::endl;
        BOOL ok = ConnectNamedPipe(pipe, nullptr);
        if (!ok) {
            DWORD err = GetLastError();
            if (err != ERROR_PIPE_CONNECTED) {
                std::wcerr << L"[server] ConnectNamedPipe failed: " << err << std::endl;
                CloseHandle(pipe);
                if (once) return 3;
                continue;
            }
        }
        std::wcout << L"[server] Client connected" << std::endl;

        std::vector<char> buffer(64 * 1024);
        while (true) {
            DWORD bytesRead = 0;
            ok = ReadFile(pipe, buffer.data(), static_cast<DWORD>(buffer.size()), &bytesRead, nullptr);
            if (!ok) {
                DWORD err = GetLastError();
                if (err == ERROR_MORE_DATA) {
                    buffer.resize(buffer.size() * 2);
                    continue;
                }
                std::wcout << L"[server] Read end: " << err << std::endl;
                break;
            }
            if (bytesRead == 0) {
                std::wcout << L"[server] Client closed" << std::endl;
                break;
            }
            std::string recv(buffer.data(), buffer.data() + bytesRead);
            std::wcout << L"[server] RX: " << std::wstring(recv.begin(), recv.end()) << std::endl;

            std::string reply = std::string("{\"kind\":\"pong\",\"echo\":") + recv + "}";
            DWORD bytesWritten = 0;
            ok = WriteFile(pipe, reply.data(), static_cast<DWORD>(reply.size()), &bytesWritten, nullptr);
            std::wcout << L"[server] TX status: " << (ok ? L"ok" : L"err") << L", bytes=" << bytesWritten << std::endl;
            if (!ok) break;
        }

        FlushFileBuffers(pipe);
        DisconnectNamedPipe(pipe);
        CloseHandle(pipe);
        std::wcout << L"[server] Disconnected" << std::endl;
        if (once) break;
    }

    return 0;
}

int wmain(int argc, wchar_t* argv[]) {
    std::wstring pipe = L""; // use default unless overridden
    std::string json = "{\"kind\":\"ping\",\"source\":\"harness\"}";
    bool server = false;
    bool once = false;
    bool sendState = false;

    for (int i = 1; i < argc; ++i) {
        std::wstring arg = argv[i];
        if (arg == L"--pipe" && i + 1 < argc) {
            pipe = argv[++i];
        } else if (arg == L"--json" && i + 1 < argc) {
            std::wstring w = argv[++i];
            json.assign(w.begin(), w.end());
        } else if (arg == L"--state") {
            sendState = true;
        } else if (arg == L"--server") {
            server = true;
        } else if (arg == L"--once") {
            once = true;
        } else if (arg == L"--help" || arg == L"-h") {
            usage();
            return 0;
        }
    }

    std::wstring use_pipe = pipe.empty() ? L"\\\\.\\pipe\\civv_llm" : pipe;

    if (server) {
        return run_server(use_pipe, once);
    }

    SetEnvironmentVariableW(L"CIVV_PIPE", use_pipe.c_str());
    std::wcout << L"Using pipe: " << use_pipe << std::endl;

    if (!llmbridge::LLMBridge_Initialize()) {
        std::wcerr << L"Initialize failed" << std::endl;
        return 1;
    }

    // Wait a bit for connection (up to ~5 seconds)
    for (int i = 0; i < 50; ++i) {
        if (llmbridge::LLMBridge_IsConnected()) {
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    bool connected = llmbridge::LLMBridge_IsConnected();
    std::wcout << L"Connected: " << (connected ? L"yes" : L"no") << std::endl;

    bool sent = false;
    if (sendState) {
        // Just print the JSON directly to verify serialization works
        std::string state = GameStateSerializer::serializeGameLevelInfo();
        std::cout << "\n=== Game Level Info JSON ===\n" << state << "\n============================\n" << std::endl;
        sent = llmbridge::LLMBridge_Send(state.c_str());
    } else {
        sent = llmbridge::LLMBridge_Send(json.c_str());
    }
    std::wcout << L"Send returned: " << (sent ? L"true" : L"false") << std::endl;

    // Allow background threads to process and send the message
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));

    llmbridge::LLMBridge_Shutdown();
    std::wcout << L"Shutdown complete" << std::endl;
    return 0;
}
