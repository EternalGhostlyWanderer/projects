#ifndef READER_H
#define READER_H
#include "../waveform/waveform.h"
#include <fstream>
#include <string>

class WavReader
{
public:
    static Waveform read(const std::string& path);
};

#endif  // READER_H
