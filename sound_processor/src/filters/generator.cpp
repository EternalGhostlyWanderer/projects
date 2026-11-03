#include "generator.h"
#include <algorithm>
#include <cmath>

SinGenFilter::SinGenFilter(double frequency, double duration)
    : _frequency(frequency), _duration(duration)
{
    std::string helpText = std::string(FilterDocs::getHelp("sin"));
    if(frequency < 0 || duration < 0)
        throw std::logic_error("Invalid argument for sin generator!\n" +
                               helpText);
}

void SinGenFilter::apply(Waveform* sound)
{
    size_t duration = (_duration / 1000 * Waveform::SAMPLE_RATE);
    std::vector<int16_t>& samples = sound->getSamples();
    samples.resize(duration);
    for(size_t i = 0; i < duration; i++)
    {
        double newValue =
            32767 * sin(2 * M_PI * _frequency * (i / Waveform::SAMPLE_RATE));
        samples[i] = std::clamp(newValue, -32768.0, 32767.0);
    }
}

AmGenFilter::AmGenFilter(double amplitude, double carrier, double modulation,
                         double depth, double duration)
    : _amplitude(amplitude), _carrier(carrier), _modulation(modulation),
      _depth(depth), _duration(duration)
{
    std::string helpText = std::string(FilterDocs::getHelp("am"));
    if(amplitude < 0 || amplitude > 1 || carrier < 0 || modulation < 0 ||
       depth < 0 || depth > 1 || duration < 0)
        throw std::logic_error("Invalid argument for am generator!\n" +
                               helpText);
}

void AmGenFilter::apply(Waveform* sound)
{
    size_t duration = (_duration / 1000 * Waveform::SAMPLE_RATE);
    std::vector<int16_t>& samples = sound->getSamples();
    samples.resize(duration);

    for(size_t i = 0; i < duration; i++)
    {
        double envelope = 1 + _depth * sin(2 * M_PI * _modulation *
                                           (i / Waveform::SAMPLE_RATE));
        double carrier = sin(2 * M_PI * _carrier * (i / Waveform::SAMPLE_RATE));
        double newValue = 32767 * _amplitude * envelope * carrier;
        samples[i] = std::clamp(newValue, -32768.0, 32767.0);
    }
}

FmGenFilter::FmGenFilter(double amplitude, double carrier, double modulation,
                         double deviation, double duration)
    : _amplitude(amplitude), _carrier(carrier), _modulation(modulation),
      _deviation(deviation), _duration(duration)
{
    std::string helpText = std::string(FilterDocs::getHelp("fm"));
    if(amplitude < 0 || amplitude > 1 || carrier < 0 || modulation <= 0 ||
       deviation < 0 || duration < 0)
        throw std::logic_error("Invalid argument for fm generator!\n" +
                               helpText);
}

void FmGenFilter::apply(Waveform* sound)
{
    size_t duration = (_duration / 1000 * Waveform::SAMPLE_RATE);
    std::vector<int16_t>& samples = sound->getSamples();
    samples.resize(duration);

    for(size_t i = 0; i < duration; i++)
    {
        double phase =
            2 * M_PI * _carrier * (i / Waveform::SAMPLE_RATE) +
            (_deviation / _modulation) *
                sin(2 * M_PI * _modulation * (i / Waveform::SAMPLE_RATE));
        double newValue = 32767 * _amplitude * sin(phase);
        samples[i] = std::clamp(newValue, -32768.0, 32767.0);
    }
}