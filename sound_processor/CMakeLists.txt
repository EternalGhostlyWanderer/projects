cmake_minimum_required(VERSION 3.30)
project(sound_processor)

set(CMAKE_CXX_STANDARD 20)

add_executable(sound_processor src/main.cpp
        src/cmd_args_parser/cmd_args_parser.cpp
        src/waveform/waveform.cpp
        src/read_and_write/reader.cpp
        src/read_and_write/writer.cpp
        src/pipeline/pipeline.cpp
        src/cmd_args_parser/pipeline_builder.cpp
        src/application.cpp
        src/cmd_args_parser/cmd_args_parser.cpp
        src/filters/ampl.cpp
        src/filters/generator.cpp
        src/filters/normalize.cpp
        src/filters/silence.cpp
        src/filters/timestretch.cpp
        src/filters/lowpass.cpp
        src/filters/filters.cpp
        src/read_and_write/structs.cpp
        src/cmd_args_parser/std_filter_producers.cpp
        src/filter_descriptor.cpp
)
if (MINGW)
    target_link_options(${PROJECT_NAME} PRIVATE "-static-libgcc" "-static-libstdc++" "-static")
endif ()

add_subdirectory(tests)