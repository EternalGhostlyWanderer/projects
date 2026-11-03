#include "filters.h"
#include "generator.h"
#include <catch2/catch_amalgamated.hpp>

TEST_CASE("AmplFilter: incorrect arguments")
{
    REQUIRE_THROWS_AS(AmplFilter(-1), std::logic_error);
}

TEST_CASE("NormFilter: incorrect arguments")
{
    SECTION("negative peak")
    {
        REQUIRE_THROWS_AS(NormFilter(-1), std::logic_error);
    }

    SECTION("peak > 1") { REQUIRE_THROWS_AS(NormFilter(2), std::logic_error); }
}

TEST_CASE("SilenceFilter: incorrect arguments")
{
    SECTION("invalid unit")
    {
        REQUIRE_THROWS_AS(SilenceFilter("s", 1, 2), std::logic_error);
    }

    SECTION("negative start")
    {
        REQUIRE_THROWS_AS(SilenceFilter("sec", -1, 2), std::logic_error);
    }

    SECTION("start > end")
    {
        REQUIRE_THROWS_AS(SilenceFilter("sec", 3, 2), std::logic_error);
    }
}

TEST_CASE("TimestretchFilter: incorrect arguments")
{
    REQUIRE_THROWS_AS(TimestretchFilter(0), std::logic_error);
}

TEST_CASE("LowpassFilter: incorrect arguments")
{
    REQUIRE_THROWS_AS(LowpassFilter(0), std::logic_error);
}

TEST_CASE("SinGenFilter: incorrect arguments")
{
    SECTION("negative frequency")
    {
        REQUIRE_THROWS_AS(SinGenFilter(-440, 1000), std::logic_error);
    }

    SECTION("negative duration")
    {
        REQUIRE_THROWS_AS(SinGenFilter(440, -1000), std::logic_error);
    }
}

TEST_CASE("AmGenFilter: incorrect arguments")
{
    SECTION("negative amplitude")
    {
        REQUIRE_THROWS_AS(AmGenFilter(-0.5, 440, 4, 0.5, 1000),
                          std::logic_error);
    }

    SECTION("amplitude > 1")
    {
        REQUIRE_THROWS_AS(AmGenFilter(1.5, 440, 4, 0.5, 1000),
                          std::logic_error);
    }

    SECTION("negative carrier")
    {
        REQUIRE_THROWS_AS(AmGenFilter(0.5, -440, 4, 0.5, 1000),
                          std::logic_error);
    }

    SECTION("negative modulation")
    {
        REQUIRE_THROWS_AS(AmGenFilter(0.5, 440, -4, 0.5, 1000),
                          std::logic_error);
    }

    SECTION("negative depth")
    {
        REQUIRE_THROWS_AS(AmGenFilter(0.5, 440, 4, -0.5, 1000),
                          std::logic_error);
    }

    SECTION("depth > 1")
    {
        REQUIRE_THROWS_AS(AmGenFilter(0.5, 440, 4, 1.5, 1000),
                          std::logic_error);
    }

    SECTION("negative duration")
    {
        REQUIRE_THROWS_AS(AmGenFilter(0.5, 440, 4, 0.5, -1000),
                          std::logic_error);
    }
}

TEST_CASE("FmGenFilter: incorrect arguments")
{
    SECTION("negative amplitude")
    {
        REQUIRE_THROWS_AS(FmGenFilter(-0.5, 440, 4, 5, 1000), std::logic_error);
    }

    SECTION("amplitude > 1")
    {
        REQUIRE_THROWS_AS(FmGenFilter(1.5, 440, 4, 5, 1000), std::logic_error);
    }

    SECTION("negative carrier")
    {
        REQUIRE_THROWS_AS(FmGenFilter(0.5, -440, 4, 5, 1000), std::logic_error);
    }

    SECTION("incorrect modulation")
    {
        REQUIRE_THROWS_AS(FmGenFilter(0.5, 440, 0, 5, 1000), std::logic_error);
    }

    SECTION("negative deviation")
    {
        REQUIRE_THROWS_AS(FmGenFilter(0.5, 440, 4, -5, 1000), std::logic_error);
    }

    SECTION("negative duration")
    {
        REQUIRE_THROWS_AS(FmGenFilter(0.5, 440, 4, 5, -1000), std::logic_error);
    }
}