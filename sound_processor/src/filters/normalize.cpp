#include "filters.h"
#include <algorithm>

NormFilter::NormFilter(double peak): _peak{peak}
{
    std::string helpText = std::string(FilterDocs::getHelp("normalize"));
    if(peak < 0 || peak > 1)
        throw std::logic_error("The [peak] argument for normalize "
                               "filter must be between 0 and 1!\n" +
                               helpText);
}

void NormFilter::apply(Waveform* sound)
{
    std::vector<int16_t>& samples = sound->getSamples();
    if(samples.empty())
        return;
    int currentPeak = 0;
    for(int16_t sample: samples)
        if(std::abs(sample) > currentPeak)
            currentPeak = std::abs(sample);
    double scale = _peak * 32767 / currentPeak;

    for(int16_t& sample: samples)
        sample = std::clamp(sample * scale, -32768.0, 32767.0);
}
