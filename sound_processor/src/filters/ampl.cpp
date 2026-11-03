#include "filters.h"
#include <algorithm>
AmplFilter::AmplFilter(double ampl): _factor(ampl)
{
    std::string helpText = std::string(FilterDocs::getHelp("ampl"));
    if(ampl < 0)
        throw std::logic_error(
            "First argument for ampl filter cannot be negative!\n" + helpText);
}

void AmplFilter::apply(Waveform* sound)
{
    for(int16_t& sample: sound->getSamples())
    {
        double newValue = sample * _factor;
        sample = std::clamp(newValue, -32768.0, 32767.0);
    }
}
