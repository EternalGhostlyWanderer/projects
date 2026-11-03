#ifndef WRITER_H
#define WRITER_H
#include "../waveform/waveform.h"
#include <string>

class WavWriter
{
public:
    static void write(const Waveform& waveform, const std::string& path);
};

#endif  // WRITER_H
