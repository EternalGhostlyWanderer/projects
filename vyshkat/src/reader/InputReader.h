#pragma once

#include <stdexcept>
#include <string>

// Бросается, когда поток ввода закончился (Ctrl+D / Ctrl+Z).
class InputEnded : public std::runtime_error {
public:
    InputEnded() : std::runtime_error("Input stream ended") {}
};

class InputReader {
public:
    virtual ~InputReader() = default;

    virtual std::string readString(const std::string& prompt) = 0;
    virtual int readInt(const std::string& prompt) = 0;
    virtual double readDouble(const std::string& prompt) = 0;
};
