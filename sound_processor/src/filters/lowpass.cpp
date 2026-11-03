#include "filters.h"
#include <cmath>

LowpassFilter::LowpassFilter(int windowSize): _windowSize(windowSize)
{
    std::string helpText = std::string(FilterDocs::getHelp("lowpass"));
    if(windowSize <= 0)
        throw std::logic_error("Invalid argument for lowpass filter!\n" +
                               helpText);
}

void LowpassFilter::apply(Waveform* sound)
{
    std::vector<int16_t>& samples = sound->getSamples();
    std::vector<int16_t> temp(samples.size());

    int rad = (_windowSize - 1) / 2;

    for(size_t i = 0; i < samples.size(); i++)
    {
        double sum = 0;
        for(int j = -rad; j <= rad; j++)
            if(j + i < 0)
                sum += samples[0];
            else if(j + i > samples.size())
                sum += samples[samples.size() - 1];
            else
                sum += samples[i + j];
        temp[i] = round(sum / _windowSize);
    }
    samples.swap(temp);
}