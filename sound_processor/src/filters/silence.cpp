#include "filters.h"

SilenceFilter::SilenceFilter(std::string_view unit, double start, double end)
    : _unit(unit), _start(start), _end(end)
{
    std::string helpText = std::string(FilterDocs::getHelp("silence"));
    if(unit != "sec" && unit != "ms")
        throw std::logic_error("Invalid time unit for filter 'silence'.\n "
                               "Expected: (sec|ms)\n" +
                               helpText);
    if(start < 0)
        throw std::logic_error("The <start> value cannot be negative.\n" +
                               helpText);
    if(start >= end)
    {
        throw std::logic_error(
            "The <start> time must be strictly less than <end> time.\n" +
            helpText);
    }
}

void SilenceFilter::apply(Waveform* sound)
{
    std::vector<int16_t>& samples = sound->getSamples();
    double start, end;

    if(_unit == "sec")
    {
        start = _start;
        end = _end;
    }
    else if(_unit == "mc")
    {
        start = _start / 1000;
        end = _end / 1000;
    }
    // else//должен был отловить silenceProducer
    //     return;
    size_t startIdx = (start * Waveform::SAMPLE_RATE);
    size_t endIdx = (end * Waveform::SAMPLE_RATE);

    if(startIdx >= samples.size())
        samples.resize(endIdx, 0);
    else
        samples.insert(samples.begin() + startIdx, endIdx - startIdx, 0);
}