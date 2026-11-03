#include "waveform.h"

Waveform::Waveform() = default;
Waveform::Waveform(size_t size): _samples(size) {}
Waveform::Waveform(const std::vector<int16_t>& values) { _samples = values; }
size_t Waveform::size() const { return _samples.size(); }

void Waveform::setSample(size_t i, int16_t value) { _samples[i] = value; }
const int16_t* Waveform::getSample(size_t i) const { return &_samples[i]; }
