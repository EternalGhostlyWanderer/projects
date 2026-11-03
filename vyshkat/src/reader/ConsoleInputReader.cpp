#include "ConsoleInputReader.h"

#include <cstddef>
#include <stdexcept>

namespace {

bool onlySpacesAfter(const std::string& line, std::size_t pos) {
    return line.find_first_not_of(" \t", pos) == std::string::npos;
}

}  // namespace

ConsoleInputReader::ConsoleInputReader(std::istream& in, std::ostream& out)
    : in_(in), out_(out) {}

std::string ConsoleInputReader::readString(const std::string& prompt) {
    out_ << prompt;

    std::string value;

    if (!std::getline(in_, value)) {
        throw InputEnded();
    }

    return value;
}

int ConsoleInputReader::readInt(const std::string& prompt) {
    while (true) {
        const std::string line = readString(prompt);

        try {
            std::size_t pos = 0;
            const int value = std::stoi(line, &pos);

            if (onlySpacesAfter(line, pos)) {
                return value;
            }
        } catch (const std::invalid_argument&) {
        } catch (const std::out_of_range&) {
        }

        out_ << "Введите целое число.\n";
    }
}

double ConsoleInputReader::readDouble(const std::string& prompt) {
    while (true) {
        const std::string line = readString(prompt);

        try {
            std::size_t pos = 0;
            const double value = std::stod(line, &pos);

            if (onlySpacesAfter(line, pos)) {
                return value;
            }
        } catch (const std::invalid_argument&) {
        } catch (const std::out_of_range&) {
        }

        out_ << "Введите число.\n";
    }
}
