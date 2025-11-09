#pragma once

#include <windows.h>
#include <string>
#include <queue>

class NamedPipeClient {
public:
    typedef void (*ReceiveCallback)(const std::string&);

    NamedPipeClient();
    ~NamedPipeClient();

    bool start(const std::wstring& pipe_name, ReceiveCallback on_receive);
    void stop();

    // Queues data to send on background thread.
    bool send(const std::string& json);

    bool is_connected() const { return connected_flag_ != 0; }

private:
    static unsigned __stdcall reader_entry(void* param);
    static unsigned __stdcall writer_entry(void* param);
    void reader_thread_proc();
    void writer_thread_proc();
    bool connect_pipe();
    void close_pipe();
    void ensure_sync_objects();
    void destroy_sync_objects();
    bool is_running() const;

    std::wstring pipe_name_;
    HANDLE pipe_;
    HANDLE reader_thread_;
    HANDLE writer_thread_;
    HANDLE queue_event_;
    CRITICAL_SECTION queue_cs_;
    volatile LONG running_flag_;
    volatile LONG connected_flag_;
    bool sync_initialized_;

    std::queue<std::string> queue_;

    ReceiveCallback on_receive_;
};
