#include "pipeline_builder.h"
#include "std_filter_producers.h"
#include <catch2/catch_amalgamated.hpp>

TEST_CASE("PipelineBuilder: createPipeline")
{
    PipelineBuilder builder;

    SECTION("Unknown filter")
    {
        std::vector<FilterDescriptor> descriptors = {{"cheremsha", {"67"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }
    SECTION("Unknown generator")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"generator", {"beda 440 2000"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }
}

TEST_CASE("PipelineBuilder: correct filter parameters")
{
    PipelineBuilder builder;
    builder.addFilterProducer("ampl", FilterProducers::amplFilterCreator);
    builder.addFilterProducer("normalize", FilterProducers::normFilterCreator);
    builder.addFilterProducer("silence", FilterProducers::silenceFilterCreator);
    builder.addFilterProducer("timestretch",
                              FilterProducers::timestretchFilterCreator);
    builder.addFilterProducer("lowpass", FilterProducers::lowpassFilterCreator);
    builder.addFilterProducer("sin",
                              FilterProducers::generatorSinFilterCreator);
    builder.addFilterProducer("am", FilterProducers::generatorAmFilterCreator);
    builder.addFilterProducer("fm", FilterProducers::generatorFmFilterCreator);

    SECTION("ampl")
    {
        std::vector<FilterDescriptor> descriptors = {{"ampl", {"2.0"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }

    SECTION("normalize")
    {
        std::vector<FilterDescriptor> descriptors = {{"normalize", {"0.8"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }
    SECTION("normalize without a peak")
    {
        std::vector<FilterDescriptor> descriptors = {{"normalize", {}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }

    SECTION("silence")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"silence", {"sec", "1.0", "2.0"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }

    SECTION("timestretch")
    {
        std::vector<FilterDescriptor> descriptors = {{"timestretch", {"1.5"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }

    SECTION("lowpass")
    {
        std::vector<FilterDescriptor> descriptors = {{"lowpass", {"5"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 1);
    }

    SECTION("multiple filters chained")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"ampl", {"2.0"}}, {"normalize", {"0.8"}}, {"lowpass", {"5"}}};
        Pipeline pipeline = builder.createPipeline(descriptors);
        REQUIRE(pipeline.getFilterNumbers() == 3);
    }

    SECTION("sin")
{
    std::vector<FilterDescriptor> descriptors = {{"sin", {"sin", "440", "1000"}}};
    Pipeline pipeline = builder.createPipeline(descriptors);
    REQUIRE(pipeline.getFilterNumbers() == 1);
}

SECTION("am")
{
    std::vector<FilterDescriptor> descriptors = {{"am", {"am", "0.5", "440", "4", "0.5", "1000"}}};
    Pipeline pipeline = builder.createPipeline(descriptors);
    REQUIRE(pipeline.getFilterNumbers() == 1);
}

SECTION("fm")
{
    std::vector<FilterDescriptor> descriptors = {{"fm", {"fm", "0.5", "440", "4", "5", "1000"}}};
    Pipeline pipeline = builder.createPipeline(descriptors);
    REQUIRE(pipeline.getFilterNumbers() == 1);
}
}

TEST_CASE("PipelineBuilder: incorrect filter parameters")
{
    PipelineBuilder builder;
    builder.addFilterProducer("ampl", FilterProducers::amplFilterCreator);
    builder.addFilterProducer("normalize", FilterProducers::normFilterCreator);
    builder.addFilterProducer("silence", FilterProducers::silenceFilterCreator);
    builder.addFilterProducer("timestretch",
                              FilterProducers::timestretchFilterCreator);
    builder.addFilterProducer("lowpass", FilterProducers::lowpassFilterCreator);
    builder.addFilterProducer("sin",
                              FilterProducers::generatorSinFilterCreator);
    builder.addFilterProducer("am", FilterProducers::generatorAmFilterCreator);
    builder.addFilterProducer("fm", FilterProducers::generatorFmFilterCreator);

    SECTION("ampl with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"ampl", {"1.0", "2.0"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("ampl with string factor")
    {
        std::vector<FilterDescriptor> descriptors = {{"ampl", {"string"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("normalize with string peak")
    {
        std::vector<FilterDescriptor> descriptors = {{"normalize", {"string"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("normalize with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"normalize", {"0.5", "1.0"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("silence with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"silence", {"sec", "1.0"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("silence with wrong arguments")
    {
        SECTION("invalid start")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"silence", {"sec", "string", "2.0"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }

        SECTION("invalid end")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"silence", {"sec", "1.0", "string"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
    }

    SECTION("timestretch with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"timestretch", {"1.0", "2.0"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("timestretch with string factor")
    {
        std::vector<FilterDescriptor> descriptors = {
            {"timestretch", {"string"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("lowpass with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"lowpass", {}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("lowpass with string window size")
    {
        std::vector<FilterDescriptor> descriptors = {{"lowpass", {"string"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("sin with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"sin", {"sin", "440"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("sin with wrong arguments")
    {
        SECTION("invalid freq")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"sin", {"sin", "string", "440"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }

        SECTION("invalid durat")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"sin", {"sin", "440", "string"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
    }

    SECTION("am with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"am", {"am","0.5", "440"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("am with string parameter")
    {
        SECTION("invalid ampl")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"am", {"am","string", "0.6", "4", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid carr")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"am", {"am","0.5", "string", "4", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid modul")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"am", {"am","0.5", "0.1", "string", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid depth")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"am", {"am","0.5", "0", "4", "string", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid durat")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"am", {"am","0.5", "0", "4", "0.5", "string"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
    }

    SECTION("fm with wrong arguments count")
    {
        std::vector<FilterDescriptor> descriptors = {{"fm", {"fm", "0.5", "440"}}};
        REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                          std::logic_error);
    }

    SECTION("fm with string parameter")
    {
        SECTION("invalid ampl")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"fm", {"fm", "string", "0.6", "4", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid carr")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"fm", {"fm", "0.5", "string", "4", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid modul")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"fm", {"fm", "0.5", "0.1", "string", "0.5", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid devi")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"fm", {"fm", "0.5", "0", "4", "string", "1000"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
        SECTION("invalid durat")
        {
            std::vector<FilterDescriptor> descriptors = {
                {"fm", {"fm", "0.5", "0", "4", "0.5", "string"}}};
            REQUIRE_THROWS_AS(builder.createPipeline(descriptors),
                              std::logic_error);
        }
    }
}