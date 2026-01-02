#include "Logger.h"

#include <windows.h>
#include <shlobj.h>
#include <cstdio>
#include <fstream>
#include <sstream>

namespace {
    std::wofstream log_file;
    CRITICAL_SECTION log_cs;
    bool log_cs_initialized = false;

    std::wstring timestamp() {
        SYSTEMTIME st; GetLocalTime(&st);
        wchar_t buf[64];
        swprintf_s(buf, L"%04u-%02u-%02u %02u:%02u:%02u.%03u",
                   st.wYear, st.wMonth, st.wDay,
                   st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
        return buf;
    }

    std::wstring ensure_log_path() {
        wchar_t appdata[MAX_PATH];
        if (SHGetFolderPathW(NULL, CSIDL_LOCAL_APPDATA, NULL, 0, appdata) != S_OK) {
            return L"llmbridge.log";
        }
        std::wstring dir = std::wstring(appdata) + L"\\LLMCiv";
        CreateDirectoryW(dir.c_str(), NULL);
        return dir + L"\\llmbridge.log";
    }
    class CritSecGuard {
    public:
        explicit CritSecGuard(CRITICAL_SECTION* cs) : cs_(cs) {
            if (cs_) {
                EnterCriticalSection(cs_);
            }
        }
        ~CritSecGuard() {
            if (cs_) {
                LeaveCriticalSection(cs_);
            }
        }
    private:
        CRITICAL_SECTION* cs_;
    };

    void ensure_lock() {
        if (!log_cs_initialized) {
            InitializeCriticalSection(&log_cs);
            log_cs_initialized = true;
        }
    }
}

namespace logger {

void init() {
    ensure_lock();
    CritSecGuard guard(&log_cs);
    if (!log_file.is_open()) {
        std::wstring path = ensure_log_path();
        log_file.open(path.c_str(), std::ios::out | std::ios::app);
    }
}

void shutdown() {
    if (!log_cs_initialized) return;
    CritSecGuard guard(&log_cs);
    if (log_file.is_open()) {
        log_file.flush();
        log_file.close();
    }
}

static void write_line(const std::wstring& level, const std::wstring& msg) {
    if (!log_cs_initialized) return;
    CritSecGuard guard(&log_cs);
    if (!log_file.is_open()) return;
    log_file << L"[" << timestamp() << L"][" << level << L"] " << msg << std::endl;
}

void info(const std::wstring& msg) { write_line(L"INFO", msg); }
void error(const std::wstring& msg) { write_line(L"ERROR", msg); }

void info(const std::string& msg) {
    std::wstring w(msg.begin(), msg.end());
    info(w);
}
void error(const std::string& msg) {
    std::wstring w(msg.begin(), msg.end());
    error(w);
}

}
