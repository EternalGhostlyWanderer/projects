#pragma once

#include <iostream>
#include <sstream>
#include <string>
// Перехватывает std::cout на время жизни объекта.
class CoutCapture {
public:
    CoutCapture() : old_(std::cout.rdbuf(stream_.rdbuf())) {}
    ~CoutCapture() { std::cout.rdbuf(old_); }

    CoutCapture(const CoutCapture&) = delete;
    CoutCapture& operator=(const CoutCapture&) = delete;

    std::string str() const { return stream_.str(); }

private:
    std::ostringstream stream_;
    std::streambuf* old_;
};
