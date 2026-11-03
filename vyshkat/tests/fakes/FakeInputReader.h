#pragma once

#include <cstddef>
#include <string>
#include <utility>
#include <vector>
#include "reader/InputReader.h"

// Подмена ввода: отдаёт заранее заданные ответы по порядку.
class FakeInputReader : public InputReader {
public:
    explicit FakeInputReader(std::vector<std::string> answers)
        : answers_(std::move(answers)) {}

    std::string readString(const std::string&) override { return next(); }
    int readInt(const std::string&) override { return std::stoi(next()); }
    double readDouble(const std::string&) override { return std::stod(next()); }

    std::size_t remaining() const { return answers_.size() - position_; }

private:
    std::vector<std::string> answers_;
    std::size_t position_ = 0;

    std::string next() {
        if (position_ >= answers_.size()) {
            throw InputEnded();
        }

        return answers_[position_++];
    }
};
