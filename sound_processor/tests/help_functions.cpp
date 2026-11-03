#include "help_functions.h"
#include <cstring>
#include <memory>
#include <sstream>

std::vector<char*> createArgv(const std::string& commandLine)
{
    std::vector<char*> argv;
    std::stringstream ss(commandLine);
    std::string token;

    while(ss >> token)
    {
        std::unique_ptr<char[]> arg(new char[token.size() + 1]);
        std::strcpy(arg.get(), token.c_str());
        argv.push_back(arg.release());
    }

    return argv;
}

void freeArgv(std::vector<char*>& argv)
{
    for(char* arg: argv)
        delete[] arg;
    argv.clear();
}
