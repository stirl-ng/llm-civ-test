#pragma once

#include <string>
#include <sstream>
#include <vector>
#include <cstdio>

// Simple JSON builder for use without RapidJSON dependency.
// This is a lightweight, header-only implementation suitable for serializing
// game state data. It does not parse JSON, only builds it.
//
// Usage:
//   JsonBuilder json;
//   json.startObject();
//   json.addString("kind", "state");
//   json.addInt("turn", 42);
//   json.startObject("data");
//   json.addBool("active", true);
//   json.endObject();
//   json.endObject();
//   std::string result = json.str();

class JsonBuilder {
public:
    JsonBuilder() : first_in_scope_(true), depth_(0) {}

    // Start a JSON object (optionally with a key if inside another object)
    void startObject(const char* key = nullptr) {
        addCommaIfNeeded();
        if (key) {
            ss_ << '"' << escapeString(key) << "\":";
        }
        ss_ << '{';
        first_in_scope_ = true;
        depth_++;
    }

    // End current JSON object
    void endObject() {
        ss_ << '}';
        first_in_scope_ = false;
        depth_--;
    }

    // Start a JSON array (optionally with a key if inside an object)
    void startArray(const char* key = nullptr) {
        addCommaIfNeeded();
        if (key) {
            ss_ << '"' << escapeString(key) << "\":";
        }
        ss_ << '[';
        first_in_scope_ = true;
        depth_++;
    }

    // End current JSON array
    void endArray() {
        ss_ << ']';
        first_in_scope_ = false;
        depth_--;
    }

    // Add a string value
    void addString(const char* key, const char* value) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(key) << "\":\"" << escapeString(value ? value : "") << '"';
    }

    void addString(const char* key, const std::string& value) {
        addString(key, value.c_str());
    }

    // Add string value to array (no key)
    void addStringValue(const char* value) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(value ? value : "") << '"';
    }

    // Add an integer value
    void addInt(const char* key, int value) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(key) << "\":" << value;
    }

    // Add integer value to array (no key)
    void addIntValue(int value) {
        addCommaIfNeeded();
        ss_ << value;
    }

    // Add a boolean value
    void addBool(const char* key, bool value) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(key) << "\":" << (value ? "true" : "false");
    }

    // Add boolean value to array (no key)
    void addBoolValue(bool value) {
        addCommaIfNeeded();
        ss_ << (value ? "true" : "false");
    }

    // Add a null value
    void addNull(const char* key) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(key) << "\":null";
    }

    // Add null value to array (no key)
    void addNullValue() {
        addCommaIfNeeded();
        ss_ << "null";
    }

    // Add a double/float value
    void addDouble(const char* key, double value) {
        addCommaIfNeeded();
        char buf[64];
        snprintf(buf, sizeof(buf), "%.6g", value);
        ss_ << '"' << escapeString(key) << "\":" << buf;
    }

    // Add raw JSON (must be valid JSON, not escaped)
    void addRaw(const char* key, const char* rawJson) {
        addCommaIfNeeded();
        ss_ << '"' << escapeString(key) << "\":" << (rawJson ? rawJson : "null");
    }

    // Get the resulting JSON string
    std::string str() const {
        return ss_.str();
    }

    // Clear and reset for reuse
    void clear() {
        ss_.str("");
        ss_.clear();
        first_in_scope_ = true;
        depth_ = 0;
    }

private:
    void addCommaIfNeeded() {
        if (!first_in_scope_) {
            ss_ << ',';
        }
        first_in_scope_ = false;
    }

    static std::string escapeString(const char* s) {
        if (!s) return "";
        std::string result;
        result.reserve(strlen(s) + 16);
        while (*s) {
            char c = *s++;
            switch (c) {
                case '"':  result += "\\\""; break;
                case '\\': result += "\\\\"; break;
                case '\b': result += "\\b"; break;
                case '\f': result += "\\f"; break;
                case '\n': result += "\\n"; break;
                case '\r': result += "\\r"; break;
                case '\t': result += "\\t"; break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20) {
                        char buf[8];
                        snprintf(buf, sizeof(buf), "\\u%04x", static_cast<unsigned char>(c));
                        result += buf;
                    } else {
                        result += c;
                    }
                    break;
            }
        }
        return result;
    }

    std::stringstream ss_;
    bool first_in_scope_;
    int depth_;
};
