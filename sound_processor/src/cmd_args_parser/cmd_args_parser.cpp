#include "cmd_args_parser.h"

#include <iostream>
bool ArgsParser::isValidArgument(int i, int argc, char* argv[])
{
    if(i > argc)
        return false;

    if(argv[i][0] == '-')
        return false;

    return true;
}
bool ArgsParser::isWavFile(std::string_view fileName)
{
    if(fileName.length() < 4)
        return false;
    std::string_view end = fileName.substr(fileName.length() - 4);
    return end == ".wav" || end == ".WAV";
}

ArgsParser::ArgsParser() {}
ArgsParser::Result ArgsParser::parse(int argc, char* argv[])
{
    bool flagI = false;
    bool flagO = false;
    bool flagF = false;

    if(argc < 2)
        return Result::noArgs;  // show help

    for(int i = 1; i < argc; i++)
    {
        if(argv[i][0] == '-')  // this is flag
        {

            if(argv[i][1] == 'i')
            {
                if(flagO || flagF || flagI)
                    return Result::invalidArgSeq;
                i++;
                if(!isValidArgument(i, argc, argv) || !isWavFile(argv[i]))
                {
                    std::cerr << "Input file must be in .wav format!"
                              << std::endl;
                    return Result::badArgs;
                }

                flagI = true;_inFileName = argv[i];
            }

            else if(argv[i][1] == 'o')
            {
                if(flagO || flagF)
                    return Result::invalidArgSeq;
                i++;
                if(!isValidArgument(i, argc, argv) || !isWavFile(argv[i]))
                {
                    std::cerr << "Output file must be in .wav format!"
                              << std::endl;
                    return Result::badArgs;
                }
                _outFileName = argv[i];
                flagO = true;
            }

            else if(argv[i][1] == 'f')
            {
                flagF = true;
                if(i + 1 < argc)
                {
                    i++;
                    std::string name = argv[i];
                    if (name[0] == '-')
                    {
                        std::cerr << "Missing filter name after -f flag!"
                              << std::endl;
                    return Result::badArgs;
                    }

                    FilterDescriptor fd(name);
                    while(i + 1 < argc && argv[i + 1][0] != '-')
                    {
                        i++;
                        fd.params.push_back(argv[i]);
                    };

                    _filterDescriptors.push_back(fd);
                }
                else
                {
                    std::cerr << "Missing filter name after -f flag!"
                              << std::endl;
                    return Result::badArgs;
                }
            }

            else
            {
                return Result::invalidFlags;
            }
        }
        else  // если даны просто параметры, но не указан ключ команды
            return Result::invalidArgSeq;
    }
    return Result::ok;
}
