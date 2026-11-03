#include "../contrib/catch2/catch_amalgamated.hpp"
#include "../src/cmd_args_parser/cmd_args_parser.h"
#include "help_functions.h"

#include <iostream>
TEST_CASE("ArgsParser")
{
    SECTION("noArgs")
    {
        ArgsParser parser;
        char program_name[] = "sound_processor.exe";
        char* argv[] = {program_name};
        int argc = 1;

        REQUIRE(parser.parse(argc, argv) == ArgsParser::Result::noArgs);
    }

    SECTION("Correct input")
    {
        ArgsParser parser;
        std::vector<char*> argv =
            createArgv("sound_processor.exe -i input.wav -o output.WAV");
        int argc = argv.size();

        REQUIRE(parser.parse(argc, argv.data()) == ArgsParser::Result::ok);
        REQUIRE(parser.getInFileName() == "input.wav");
        REQUIRE(parser.getOutFileName() == "output.WAV");
        REQUIRE(parser.getFilterDescriptors().empty());
        freeArgv(argv);
    }

    SECTION("Invalid flag")
    {
        ArgsParser parser;
        std::vector<char*> argv = createArgv("sound_processor.exe -x");
        int argc = argv.size();

        REQUIRE(parser.parse(argc, argv.data()) ==
                ArgsParser::Result::invalidFlags);
        freeArgv(argv);
    }

    SECTION("Missing flag")
    {
        ArgsParser parser;
        std::vector<char*> argv = createArgv("sound_processor.exe input.wav");
        int argc = argv.size();
        REQUIRE(parser.parse(argc, argv.data()) ==
                ArgsParser::Result::invalidArgSeq);
        freeArgv(argv);
    }

    SECTION("Incorrect flag order: -i cannot be after -o")
    {
        ArgsParser parser;
        std::vector<char*> argv =
            createArgv("sound_processor.exe -o input.wav -i output.WAV");
        int argc = argv.size();

        REQUIRE(parser.parse(argc, argv.data()) ==
                ArgsParser::Result::invalidArgSeq);
        freeArgv(argv);
    }

    SECTION("Incorrect flag order: cannot be double -i or -o flags")
    {
        ArgsParser parser;
        std::vector<char*> argv =
            createArgv("sound_processor.exe -i input.wav -i output.WAV");
        int argc = argv.size();
        REQUIRE(parser.parse(argc, argv.data()) ==
                ArgsParser::Result::invalidArgSeq);
        freeArgv(argv);
    }

    SECTION("Incorrect file format")
    {
        std::ostringstream nullStream;
        std::streambuf* oldBuf = std::cerr.rdbuf(nullStream.rdbuf());
        ArgsParser parser;
        std::vector<char*> argv =
            createArgv("sound_processor.exe -i input.txt -i output.txt");
        int argc = argv.size();
        REQUIRE(parser.parse(argc, argv.data()) == ArgsParser::Result::badArgs);
        freeArgv(argv);
        std::cerr.rdbuf(oldBuf);
    }

    SECTION("Missing filter name after -f flag")
    {
        std::ostringstream nullStream;
        std::streambuf* oldBuf = std::cerr.rdbuf(nullStream.rdbuf());
        ArgsParser parser;
        std::vector<char*> argv =
            createArgv("sound_processor.exe -f -f silence");
        int argc = argv.size();
        REQUIRE(parser.parse(argc, argv.data()) == ArgsParser::Result::badArgs);
        freeArgv(argv);
        std::cerr.rdbuf(oldBuf);
    }
}