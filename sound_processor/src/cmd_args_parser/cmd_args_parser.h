#ifndef CMDARGUMENTSPARSER_H
#define CMDARGUMENTSPARSER_H
#include "../filter_descriptor.h"

#include <vector>

class ArgsParser
{
public:
    enum class Result
    {
        ok,
        noArgs,         // show help
        invalidArgSeq,  // incorrect arguments sequence, always must be -i -o -f?
        invalidFlags,   // unknown flag
        badArgs
    };
    ArgsParser();
    ArgsParser(const ArgsParser&) = delete;
    ArgsParser& operator=(const ArgsParser&) = delete;

    Result parse(int argc, char* argv[]);

    const std::string& getInFileName() const { return _inFileName; }
    const std::string& getOutFileName() const { return _outFileName; }
    void setInFileName(std::string_view inFileName)
    {
        _inFileName = inFileName;
    }
    void setOutFileName(std::string_view outFileName)
    {
        _outFileName = outFileName;
    }
    std::vector<FilterDescriptor>& getFilterDescriptors()
    {
        return _filterDescriptors;
    }

private:
    std::string _inFileName = "";
    std::string _outFileName = "";
    std::vector<FilterDescriptor> _filterDescriptors;
    bool isValidArgument(int i, int argc, char* argv[]);
    bool isWavFile(std::string_view fileName);
};

#endif  // CMDARGUMENTSPARSER_H
