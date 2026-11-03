#ifndef WAVEFORM_H
#define WAVEFORM_H
#include <cstdint>
#include <vector>

class Waveform
{
public:
    static constexpr double SAMPLE_RATE = 44100.0;  // частота дискретизации
    static constexpr int16_t BITS_PER_SAMPLE = 16;
    static constexpr int16_t BLOCK_ALIGN = 2;
    // Количество байт в секунду = Частота дискретизации × Размер блока
    Waveform();
    explicit Waveform(size_t size);
    Waveform(const std::vector<int16_t>& values);
    size_t size() const;

    void setSample(size_t i, int16_t value);
    const int16_t* getSample(size_t i) const;
    std::vector<int16_t>& getSamples() { return _samples; }
    const std::vector<int16_t>& getSamples() const { return _samples; }

private:
    std::vector<int16_t> _samples;  // число выборок
};

#endif  // WAVEFORM_H
