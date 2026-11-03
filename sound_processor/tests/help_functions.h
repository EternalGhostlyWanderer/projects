
#ifndef HELP_FUNCTIONS_H
#define HELP_FUNCTIONS_H
#include <string>
#include <vector>

std::vector<char*> createArgv(const std::string& commandLine);
void freeArgv(std::vector<char*>& argv);

#endif  // HELP_FUNCTIONS_H
