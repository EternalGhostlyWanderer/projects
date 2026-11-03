#include "filters.h"
#include <cmath>

TimestretchFilter::TimestretchFilter(double factor): _factor{factor}
{
    std::string helpText = std::string(FilterDocs::getHelp("timestretch"));
    if(factor <= 0)
        throw std::logic_error("First argument for timestretch filter "
                               "cannot be negative or zero!\n" +
                               helpText);
}

void TimestretchFilter::apply(Waveform* sound)
{
    std::vector<int16_t>& samples = sound->getSamples();
    double newSize = round(samples.size() * _factor);
    std::vector<int16_t> temp(newSize);
    for(size_t i = 0; i < newSize; i++)
    {
        double pos = i / _factor;
        double l;
        double frac = std::modf(pos, &l);
        l = static_cast<size_t>(l);
        frac = static_cast<size_t>(frac);

        if(i == newSize - 1)
            temp[i] = samples[l] * (1 - frac) + samples[l] * frac;
        else
            temp[i] = samples[l] * (1 - frac) + samples[l + 1] * frac;
    }
    samples.swap(temp);
}