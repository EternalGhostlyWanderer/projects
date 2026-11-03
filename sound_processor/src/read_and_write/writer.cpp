#include "writer.h"

#include "structs.h"

#include <fstream>
#include <stdexcept>
#include <cstdint>

uint32_t toLittleEndian(uint32_t val) {
    return
        ((val & 0x000000FF) << 24) |
        ((val & 0x0000FF00) << 8)  |
        ((val & 0x00FF0000) >> 8)  |
        ((val & 0xFF000000) >> 24);
}

void WavWriter::write(const Waveform& waveform, const std::string& path)
{
    std::ofstream file(path, std::ios::binary);

    if(!file)
        throw std::runtime_error("Cannot open output file");

    uint32_t dataSize = waveform.size() * 2;
    RiffHeader riff{
        toLittleEndian(0x52494646), //"RIFF" (0x52494646)
        36 + dataSize,
        toLittleEndian(0x57415645) //"WAVE" (0x57415645)
    };

    FmtHeader fmt{toLittleEndian(0x666d7420), //"fmt " (0x666D7420)
        16,
        1,
        1,
        44100,
        44100 * 2,
        2,
        16};

    DataHeader data{toLittleEndian(0x64617461), // "data" (0x64617461)
                    dataSize};

    file.write(reinterpret_cast<char*>(&riff), sizeof(riff));

    file.write(reinterpret_cast<char*>(&fmt), sizeof(fmt));

    file.write(reinterpret_cast<char*>(&data), sizeof(data));

    file.write(reinterpret_cast<const char*>(waveform.getSample(0)), dataSize);
}