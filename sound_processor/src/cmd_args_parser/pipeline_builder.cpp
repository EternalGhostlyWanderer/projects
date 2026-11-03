#include "pipeline_builder.h"

#include "../filters/generator.h"
#include "std_filter_producers.h"
#include <iostream>
#include <stdexcept>
Pipeline
PipelineBuilder::createPipeline(std::vector<FilterDescriptor>& descriptors)

{
    Pipeline pipeline;
    for(FilterDescriptor& fd: descriptors)
    {
        if(fd.name == "generator")
        {
            if(fd.params[0] == "sin")
                fd.name = "sin";
            else if(fd.params[0] == "am")
                fd.name = "am";
            else if(fd.params[0] == "fm")
                fd.name = "fm";
            else
                throw std::logic_error(
                    "Invalid generator parameter! Expected sin, am, or fm.");
        }
        auto it = _producers.find(fd.name);
        if(it == _producers.end())
        {
            throw std::logic_error("Unknown filter!");
        }
        try
        {
            FilterProducer prod = it->second;
            Filter* filter = prod(fd);
            pipeline.addFilter(filter);
        }
        catch(std::logic_error& e)
        {
            throw std::logic_error(e);
        }
        catch(std::exception& e)
        {
            std::cerr << "Unusual error:" << e.what();
            throw std::exception(e);
        }
    }
    return pipeline;
}
void PipelineBuilder::addFilterProducer(std::string_view filterName,
                                        FilterProducer producer)
{
    _producers[filterName] = producer;
}
FilterProducer PipelineBuilder::getFilterProducer(std::string_view filterName)
{
    auto it = _producers.find(filterName);
    if(it == _producers.end())
        return nullptr;

    return it->second;
}
namespace FilterProducers {

Filter* amplFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 1)
        throw std::logic_error(
            "Wrong params number for ampl filter producer!\n" + helpText);

    try
    {
        double ampl = std::stod(fd.params[0]);

        Filter* amplFilter = new AmplFilter(ampl);
        return amplFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for ampl filter!\n" +
                               helpText);
    }
}

Filter* normFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));
    if(fd.params.size() > 1)
        throw std::logic_error(
            "Wrong params number for normalize filter producer!");

    try
    {
        if (fd.params.empty()) return new NormFilter();
        double peak = std::stod(fd.params[0]);

        Filter* normFilter = new NormFilter(peak);
        return normFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for normalize filter!\n" +
                               helpText);
    }
}

Filter* silenceFilterCreator(const FilterDescriptor& fd)
{
    if(fd.name != "silence")
        throw std::logic_error("Wrong fd for ampl filter producer.");
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 3)
        throw std::logic_error(
            "Wrong params number for silence filter producer.\n" + helpText);

    try
    {
        std::string_view unit = fd.params[0];

        double start = std::stod(fd.params[1]);
        double end = std::stod(fd.params[2]);

        Filter* silenceFilter = new SilenceFilter(unit, start, end);
        return silenceFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error(
            "Invalid numeric argument for silence filter!\n" + helpText);
    }
}

Filter* timestretchFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 1)
        throw std::logic_error(
            "Wrong params number for timestretch filter producer.\n" +
            helpText);

    try
    {
        double factor = std::stod(fd.params[0]);

        Filter* timestretchFilter = new TimestretchFilter(factor);
        return timestretchFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for timestretch filter!\n" +
                               helpText);
    }
}

Filter* lowpassFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 1)
        throw std::logic_error(
            "Wrong params number for lowpass filter producer.\n" + helpText);

    try
    {
        double windowSize = std::stod(fd.params[0]);

        Filter* lowpassFilter = new LowpassFilter(windowSize);
        return lowpassFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for lowpass filter!\n" +
                               helpText);
    }
}

Filter* generatorSinFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 3)
        throw std::logic_error(
            "Wrong params number for generator sin producer.\n" + helpText);

    try
    {
        double freq = std::stod(fd.params[1]);
        double durat = std::stod(fd.params[2]);

        Filter* sinFilter = new SinGenFilter(freq, durat);
        return sinFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for sin generator!\n" +
                               helpText);
    }
}

Filter* generatorAmFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 6)
        throw std::logic_error(
            "Wrong params number for generator am producer.\n" + helpText);

    try
    {
        double ampl = std::stod(fd.params[1]);
        double carr = std::stod(fd.params[2]);
        double modul = std::stod(fd.params[3]);
        double depth = std::stod(fd.params[4]);
        double durat = std::stod(fd.params[5]);

        Filter* amFilter = new AmGenFilter(ampl, carr, modul, depth, durat);
        return amFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for am generator!\n" +
                               helpText);
    }
}

Filter* generatorFmFilterCreator(const FilterDescriptor& fd)
{
    std::string helpText = std::string(FilterDocs::getHelp(fd.name));

    if(fd.params.size() != 6)
        throw std::logic_error(
            "Wrong params number for generator fm producer.\n" + helpText);

    try
    {
        double ampl = std::stod(fd.params[1]);
        double carr = std::stod(fd.params[2]);
        double modul = std::stod(fd.params[3]);
        double devi = std::stod(fd.params[4]);
        double durat = std::stod(fd.params[5]);

        Filter* fmFilter = new FmGenFilter(ampl, carr, modul, devi, durat);
        return fmFilter;
    }
    catch(std::invalid_argument& e)
    {
        throw std::logic_error("Invalid argument for fm generator!\n" +
                               helpText);
    }
}

// ...
};  // namespace FilterProducers
