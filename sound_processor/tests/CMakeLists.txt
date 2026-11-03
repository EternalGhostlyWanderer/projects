# tests/CMakeLists.txt

add_executable(sound_processor_tests
        test_arg_parser.cpp
        test_pipeline_builder.cpp
        test_filters.cpp
        test_read_and_write.cpp
        help_functions.cpp
        help_functions.h
        ../src/cmd_args_parser/cmd_args_parser.cpp
        ../src/cmd_args_parser/pipeline_builder.cpp
        ../src/cmd_args_parser/std_filter_producers.cpp
        ../src/filters/ampl.cpp
        ../src/filters/generator.cpp
        ../src/filters/normalize.cpp
        ../src/filters/silence.cpp
        ../src/filters/timestretch.cpp
        ../src/filters/lowpass.cpp
        ../src/filters/filters.cpp
        ../src/pipeline/pipeline.cpp
        ../src/read_and_write/reader.cpp
        ../src/read_and_write/writer.cpp
        ../src/waveform/waveform.cpp
        ../contrib/catch2/catch_amalgamated.cpp
)

target_include_directories(sound_processor_tests PRIVATE
        ../src/cmd_args_parser
        ../src/filters
        ../src/pipeline
        ../src/read_and_write
        ../src/waveform
        ../contrib
)

target_compile_definitions(sound_processor_tests PRIVATE CATCH_CONFIG_MAIN)