#include "reader.h"
#include "structs.h"
Waveform WavReader::read(const std::string& path)
{
    std::ifstream file(path, std::ios::binary);
    if(!file.is_open())
        throw std::runtime_error("Cannot open file");
    RiffHeader riffHdr;
    file.read(reinterpret_cast<char*>(&riffHdr), sizeof(riffHdr));

    FmtHeader fmt;
    file.read(reinterpret_cast<char*>(&fmt), sizeof(fmt));

    DataHeader data;
    file.read(reinterpret_cast<char*>(&data), sizeof(data));

    std::vector<int16_t> samples(data.chunkSize / 2);

    file.read(reinterpret_cast<char*>(&samples[0]), data.chunkSize);
    Waveform wf(samples);

    return wf;
}