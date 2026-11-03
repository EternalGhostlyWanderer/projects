cmake_minimum_required(VERSION 3.16)
project(garden_idz2 C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

find_package(Threads REQUIRED)

set(GARDEN_SOURCES
    main.c
    cmd_parser.c
    config_reader.c
    garden_map.c
    gardener.c
    simulation.c
    writer.c
)

add_executable(garden_sem ${GARDEN_SOURCES})
target_link_libraries(garden_sem PRIVATE Threads::Threads)
target_compile_options(garden_sem PRIVATE -Wall -Wextra -Wpedantic)

add_executable(garden_cv ${GARDEN_SOURCES})
target_compile_definitions(garden_cv PRIVATE USE_CV)
target_link_libraries(garden_cv PRIVATE Threads::Threads)
target_compile_options(garden_cv PRIVATE -Wall -Wextra -Wpedantic)
