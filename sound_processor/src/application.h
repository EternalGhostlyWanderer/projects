#ifndef APPLICATION_H
#define APPLICATION_H
#include "cmd_args_parser/pipeline_builder.h"
class Application
{
public:
    void configure();
    int start(int argc, char* argv[]);
    static void helpWithSeq();
    static void helpWithFiltersArg();
    static void help();

protected:
    PipelineBuilder _pipelineBuilder;
};

#endif  // APPLICATION_H
