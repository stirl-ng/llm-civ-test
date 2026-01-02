#pragma once

#include <string>

namespace logger {

void init();
void shutdown();
void info(const std::wstring& msg);
void error(const std::wstring& msg);
void info(const std::string& msg);
void error(const std::string& msg);

}

