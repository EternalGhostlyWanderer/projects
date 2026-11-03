#include <catch2/catch_amalgamated.hpp>
#include "reader.h"
#include "writer.h"
#include "waveform.h"
#include <cstdio>

TEST_CASE("WavReader: missing file")
{
    WavReader reader;
    REQUIRE_THROWS_AS(reader.read("this_file_does_not_exist.wav"), std::runtime_error);
}

TEST_CASE("WavWriter: incorrect file")
{
    WavWriter writer;
    Waveform waveform(std::vector<int16_t>{1, 2, 3});
    REQUIRE_THROWS_AS(writer.write(waveform, ""), std::runtime_error);
}

TEST_CASE("WavWriter + WavReader")
{
    WavReader reader;
    Waveform loaded = reader.read("input_test.wav");
    Waveform temp = loaded;

    WavWriter writer;
    writer.write(loaded, "output_test.wav");

    Waveform reloaded = reader.read("output_test.wav");

    REQUIRE(reloaded.size() == temp.size());
    REQUIRE(reloaded.getSamples() == temp.getSamples());
}

