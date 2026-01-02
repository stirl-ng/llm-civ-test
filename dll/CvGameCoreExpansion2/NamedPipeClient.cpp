#include "NamedPipeClient.h"
#include "Logger.h"

#include <vector>
#include <process.h>
#include <cstdio>

namespace {
    std::string format_error(const char* prefix, DWORD err) {
        char buf[32];
        _snprintf_s(buf, _TRUNCATE, "%lu", static_cast<unsigned long>(err));
        return std::string(prefix) + buf;
    }
}

NamedPipeClient::NamedPipeClient()
    : pipe_(INVALID_HANDLE_VALUE),
      reader_thread_(NULL),
      writer_thread_(NULL),
      queue_event_(NULL),
      running_flag_(0),
      connected_flag_(0),
      sync_initialized_(false),
      on_receive_(NULL) {
    ZeroMemory(&queue_cs_, sizeof(queue_cs_));
}

NamedPipeClient::~NamedPipeClient() {
    stop();
    destroy_sync_objects();
}

void NamedPipeClient::ensure_sync_objects() {
    if (sync_initialized_) return;
    InitializeCriticalSection(&queue_cs_);
    queue_event_ = CreateEventW(NULL, FALSE, FALSE, NULL);
    if (queue_event_ == NULL) {
        DeleteCriticalSection(&queue_cs_);
        logger::error("Failed to create queue event");
        return;
    }
    sync_initialized_ = true;
}

void NamedPipeClient::destroy_sync_objects() {
    if (!sync_initialized_) return;
    DeleteCriticalSection(&queue_cs_);
    if (queue_event_) {
        CloseHandle(queue_event_);
        queue_event_ = NULL;
    }
    sync_initialized_ = false;
}

unsigned __stdcall NamedPipeClient::reader_entry(void* param) {
    NamedPipeClient* self = reinterpret_cast<NamedPipeClient*>(param);
    if (self) self->reader_thread_proc();
    return 0;
}

unsigned __stdcall NamedPipeClient::writer_entry(void* param) {
    NamedPipeClient* self = reinterpret_cast<NamedPipeClient*>(param);
    if (self) self->writer_thread_proc();
    return 0;
}

bool NamedPipeClient::start(const std::wstring& pipe_name, ReceiveCallback on_receive) {
    if (is_running()) return true;
    ensure_sync_objects();
    if (!sync_initialized_) {
        return false;
    }
    pipe_name_ = pipe_name;
    on_receive_ = on_receive;
    InterlockedExchange(&running_flag_, 1);

    unsigned threadId = 0;
    reader_thread_ = reinterpret_cast<HANDLE>(_beginthreadex(NULL, 0, &NamedPipeClient::reader_entry, this, 0, &threadId));
    if (!reader_thread_) {
        InterlockedExchange(&running_flag_, 0);
        logger::error("Failed to create reader thread");
        return false;
    }

    writer_thread_ = reinterpret_cast<HANDLE>(_beginthreadex(NULL, 0, &NamedPipeClient::writer_entry, this, 0, &threadId));
    if (!writer_thread_) {
        InterlockedExchange(&running_flag_, 0);
        SetEvent(queue_event_);
        WaitForSingleObject(reader_thread_, INFINITE);
        CloseHandle(reader_thread_);
        reader_thread_ = NULL;
        logger::error("Failed to create writer thread");
        return false;
    }

    logger::info(L"NamedPipeClient started");
    return true;
}

void NamedPipeClient::stop() {
    if (!is_running()) return;
    logger::info(L"NamedPipeClient stopping");
    InterlockedExchange(&running_flag_, 0);
    if (queue_event_) {
        SetEvent(queue_event_);
    }
    // Wait for writer thread FIRST so it can finish sending queued messages
    if (writer_thread_) {
        WaitForSingleObject(writer_thread_, 2000); // Wait up to 2s for pending writes
        CloseHandle(writer_thread_);
        writer_thread_ = NULL;
    }
    // Now close the pipe
    close_pipe();
    // Then wait for reader thread
    if (reader_thread_) {
        WaitForSingleObject(reader_thread_, INFINITE);
        CloseHandle(reader_thread_);
        reader_thread_ = NULL;
    }
    logger::info(L"NamedPipeClient stopped");
}

bool NamedPipeClient::send(const std::string& json) {
    if (!is_running()) return false;
    if (json.empty() || json.size() > (1u << 20)) {
        logger::error("send: invalid size");
        return false;
    }

    // Synchronous send - write directly to pipe
    if (connected_flag_ == 0) {
        logger::error("send: not connected");
        return false;
    }

    DWORD bytesWritten = 0;
    BOOL ok = WriteFile(pipe_, json.data(), static_cast<DWORD>(json.size()), &bytesWritten, NULL);
    if (!ok || bytesWritten != json.size()) {
        DWORD err = GetLastError();
        logger::error("send WriteFile failed: " + std::to_string(err));
        return false;
    }
    logger::info("send: wrote " + std::to_string(bytesWritten) + " bytes");
    return true;
}

bool NamedPipeClient::is_running() const {
    return running_flag_ != 0;
}

bool NamedPipeClient::connect_pipe() {
    if (connected_flag_ != 0) return true;

    while (is_running()) {
        HANDLE h = CreateFileW(
            pipe_name_.c_str(),
            GENERIC_READ | GENERIC_WRITE,
            0,
            NULL,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            NULL);

        if (h != INVALID_HANDLE_VALUE) {
            pipe_ = h;
            InterlockedExchange(&connected_flag_, 1);
            logger::info(L"Connected to pipe: " + pipe_name_);
            DWORD mode = PIPE_READMODE_MESSAGE;
            SetNamedPipeHandleState(pipe_, &mode, NULL, NULL);
            return true;
        }

        DWORD err = GetLastError();
        if (err == ERROR_PIPE_BUSY) {
            WaitNamedPipeW(pipe_name_.c_str(), 1000);
        } else if (err == ERROR_FILE_NOT_FOUND) {
            Sleep(500);
        } else {
            logger::error(format_error("CreateFileW failed: ", err));
            Sleep(1000);
        }
    }
    return false;
}

void NamedPipeClient::close_pipe() {
    if (pipe_ != INVALID_HANDLE_VALUE) {
        CloseHandle(pipe_);
        pipe_ = INVALID_HANDLE_VALUE;
    }
    InterlockedExchange(&connected_flag_, 0);
}

void NamedPipeClient::reader_thread_proc() {
    std::vector<char> buffer(64 * 1024, 0);
    std::string message;
    while (is_running()) {
        if (connected_flag_ == 0) {
            if (!connect_pipe()) {
                break;
            }
        }

        DWORD bytesRead = 0;
        BOOL ok = ReadFile(pipe_, &buffer[0], static_cast<DWORD>(buffer.size()), &bytesRead, NULL);
        if (!ok) {
            DWORD err = GetLastError();
            if (err == ERROR_MORE_DATA) {
                if (bytesRead > 0) {
                    message.append(&buffer[0], bytesRead);
                }
                if (buffer.size() < (1u << 20)) {
                    buffer.resize(buffer.size() * 2);
                }
                continue;
            }

            if (err == ERROR_BROKEN_PIPE) {
                logger::error("Pipe disconnected by server");
            } else {
                logger::error(format_error("ReadFile failed: ", err));
            }
            close_pipe();
            message.clear();
            Sleep(500);
            continue;
        }

        if (bytesRead > 0) {
            message.append(&buffer[0], bytesRead);
        }

        if (!message.empty() && on_receive_) {
            const char first = message[0];
            const char last = message[message.size() - 1];
            if ((first == '{' && last == '}') || (first == '[' && last == ']')) {
                on_receive_(message);
            } else {
                logger::error("Dropped malformed message");
            }
        }
        message.clear();
    }
}

void NamedPipeClient::writer_thread_proc() {
    while (true) {
        std::string msg;
        bool haveMessage = false;

        EnterCriticalSection(&queue_cs_);
        if (!queue_.empty()) {
            msg = queue_.front();
            queue_.pop();
            haveMessage = true;
        }
        LeaveCriticalSection(&queue_cs_);

        // If no message and we're shutting down, exit
        if (!haveMessage && !is_running()) {
            break;
        }

        if (!haveMessage) {
            if (queue_event_) {
                WaitForSingleObject(queue_event_, 200);
            } else {
                Sleep(200);
            }
            continue;
        }

        // Have a message - try to send it
        if (connected_flag_ == 0) {
            if (!connect_pipe()) {
                // Can't connect and shutting down - drop message
                if (!is_running()) break;
                continue;
            }
        }

        DWORD bytesWritten = 0;
        BOOL ok = WriteFile(pipe_, msg.data(), static_cast<DWORD>(msg.size()), &bytesWritten, NULL);
        if (!ok || bytesWritten != msg.size()) {
            DWORD err = GetLastError();
            logger::error(format_error("WriteFile failed: ", err));
            close_pipe();

            // If shutting down, don't retry
            if (!is_running()) break;

            EnterCriticalSection(&queue_cs_);
            queue_.push(msg);
            LeaveCriticalSection(&queue_cs_);

            Sleep(200);
            continue;
        }
        logger::info("WriteFile succeeded: " + std::to_string(bytesWritten) + " bytes");
    }
}
