#ifndef STRUCTS_H
#define STRUCTS_H
#include <cstdint>

struct __attribute__((packed)) RiffHeader
{
    uint32_t chunkId; //"RIFF" (0x52494646)
    uint32_t chunkSize; //8
    uint32_t waveId; //"WAVE" (0x57415645)
};

struct __attribute__((packed)) FmtHeader
{
    uint32_t chunkId; // "fmt " (0x666D7420)
    uint32_t chunkSize; //16 байт
    uint16_t audioFormat; // PCM(1)
    uint16_t numChannels; // mono
    uint32_t sampleRate; // 44100
    uint32_t byteRate; // sampleRate * blockAlign = 44100 * 2
    uint16_t blockAlign; // numChannels * bitsPerSample/8 = 1 * 2 = 2
    uint16_t bitsPerSample; // 16
    //extraData
};
struct DataHeader {
    uint32_t chunkId; // "data" (0x64617461)
    uint32_t chunkSize;
};


#endif //STRUCTS_H
