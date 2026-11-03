#pragma once

#include <iostream>
#include <string>

#include "InputReader.h"

class ConsoleInputReader : public InputReader {
public:
    explicit ConsoleInputReader(
        std::istream& in = std::cin,
        std::ostream& out = std::cout
    );

    std::string readString(const std::string& prompt) override;
    int readInt(const std::string& prompt) override;
    double readDouble(const std::string& prompt) override;

private:
    std::istream& in_;
    std::ostream& out_;
};
