#include <gtest/gtest.h>

#include <sstream>
#include <string>

#include "reader/ConsoleInputReader.h"

namespace {

std::size_t countOccurrences(const std::string& text, const std::string& part) {
    std::size_t count = 0;
    std::size_t position = text.find(part);

    while (position != std::string::npos) {
        ++count;
        position = text.find(part, position + part.size());
    }

    return count;
}

}  // namespace

TEST(ConsoleInputReaderTest, ReadsStringAndShowsPrompt) {
    std::istringstream in("hello world\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readString("Name: "), "hello world");
    EXPECT_EQ(out.str(), "Name: ");
}

TEST(ConsoleInputReaderTest, ReadsInteger) {
    std::istringstream in("42\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readInt("N: "), 42);
}

TEST(ConsoleInputReaderTest, IntegerMayHaveSurroundingSpaces) {
    std::istringstream in("  7  \n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readInt("N: "), 7);
}

TEST(ConsoleInputReaderTest, AsksAgainAfterNonNumericInteger) {
    std::istringstream in("abc\n5\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readInt("N: "), 5);
    EXPECT_EQ(countOccurrences(out.str(), "N: "), 2U);
}

TEST(ConsoleInputReaderTest, AsksAgainWhenIntegerHasTrailingGarbage) {
    std::istringstream in("5x\n6\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readInt("N: "), 6);
}

TEST(ConsoleInputReaderTest, AsksAgainWhenIntegerIsTooLarge) {
    std::istringstream in("99999999999\n3\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_EQ(reader.readInt("N: "), 3);
}

TEST(ConsoleInputReaderTest, ReadsDouble) {
    std::istringstream in("2.5\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_NEAR(reader.readDouble("D: "), 2.5, 1e-9);
}

TEST(ConsoleInputReaderTest, AsksAgainAfterInvalidDouble) {
    std::istringstream in("x\n1.5y\n1.5\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_NEAR(reader.readDouble("D: "), 1.5, 1e-9);
    EXPECT_EQ(countOccurrences(out.str(), "D: "), 3U);
}

TEST(ConsoleInputReaderTest, EndOfInputIsReported) {
    std::istringstream in("");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_THROW(reader.readString("S: "), InputEnded);
}

TEST(ConsoleInputReaderTest, EndOfInputWhileAskingAgainIsReported) {
    std::istringstream in("abc\n");
    std::ostringstream out;
    ConsoleInputReader reader(in, out);

    EXPECT_THROW(reader.readInt("N: "), InputEnded);
}
