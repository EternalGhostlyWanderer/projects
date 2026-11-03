#include "application.h"

#include "cmd_args_parser/cmd_args_parser.h"
#include "cmd_args_parser/std_filter_producers.h"
#include "read_and_write/reader.h"
#include "read_and_write/writer.h"

#include <iostream>

void Application::configure()
{
    _pipelineBuilder.addFilterProducer("ampl",
                                       FilterProducers::amplFilterCreator);
    _pipelineBuilder.addFilterProducer("normalize",
                                       FilterProducers::normFilterCreator);
    _pipelineBuilder.addFilterProducer("silence",
                                       FilterProducers::silenceFilterCreator);
    _pipelineBuilder.addFilterProducer(
        "timestretch", FilterProducers::timestretchFilterCreator);
    _pipelineBuilder.addFilterProducer("lowpass",
                                       FilterProducers::lowpassFilterCreator);
    _pipelineBuilder.addFilterProducer(
        "sin", FilterProducers::generatorSinFilterCreator);
    _pipelineBuilder.addFilterProducer(
        "am", FilterProducers::generatorAmFilterCreator);
    _pipelineBuilder.addFilterProducer(
        "fm", FilterProducers::generatorFmFilterCreator);
}

void Application::helpWithSeq()
{
    std::cout << "\nExpected: sound_processor [-i path_to_input_file] "
                 "[-o path_to_output_file] [-f {filter_name} "
                 "[agr1_for_filter1] [agr2_for_filter1]...]...\n";
}
void Application::helpWithFiltersArg()
{
    std::cout << "\nAvailable filters and their parameters:\n";
    for(const auto& pairs: FilterDocs::HELP_MAP)
    {
        std::cout << pairs.first << "\n";
        std::cout << pairs.second << "\n";
    }
}

void Application::help()
{
    helpWithSeq();
    helpWithFiltersArg();
}

int Application::start(int argc, char* argv[])
{
    ArgsParser parser;
    ArgsParser::Result res = parser.parse(argc, argv);
    if(res != ArgsParser::Result::ok)
    {
        if(res == ArgsParser::Result::noArgs)
        {
            std::cerr << "sound_processor must have arguments!\n";
            help();
        }
        else if(res == ArgsParser::Result::invalidArgSeq)
        {
            std::cerr << "Invalid flag sequence\n";
            helpWithSeq();
        }
        else if(res == ArgsParser::Result::invalidFlags)
        {
            std::cerr << "Unknown flag!\n Expected: -i, -o, -f";
            helpWithSeq();
        }
        return 1;
    }
    std::vector<FilterDescriptor>& descriptors = parser.getFilterDescriptors();

    std::cout << "Building filter pipeline...\n";
    Pipeline pipeline;
    try
    {
        pipeline = _pipelineBuilder.createPipeline(descriptors);
    }
    catch(const std::logic_error& e)
    {
        std::cerr << e.what();
        return 2;
    }
    catch(const std::exception& e)
    {
        std::cerr << e.what();
        return 3;
    }

    Waveform sound;
    if(parser.getInFileName() != "")
        sound = WavReader::read(parser.getInFileName());

    std::cout << "Applying " << pipeline.getFilterNumbers()
              << " filter(s) to audio data...\n";
    pipeline.apply(&sound);

    std::cout << "Saving result to: " << parser.getOutFileName() << std::endl;
    if(parser.getOutFileName() != "")
        WavWriter::write(sound, parser.getOutFileName());

    std::cout << "Audio processing completed successfully!\n";
    return 0;
}
