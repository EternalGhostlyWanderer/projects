cmake_minimum_required(VERSION 3.16)

project(VyshKat LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(VYSHKAT_BUILD_TESTS "Build unit tests" ON)
option(VYSHKAT_COVERAGE "Instrument code for coverage (GCC/Clang)" OFF)

# Общие флаги только для наших целей (не для GoogleTest).
# /utf-8: без него MSVC читает исходники в системной кодировке, и русские
# строки превращаются в мусор.
add_library(vyshkat_options INTERFACE)

if(MSVC)
    target_compile_options(vyshkat_options INTERFACE /utf-8 /W4)
else()
    target_compile_options(vyshkat_options INTERFACE -Wall -Wextra -Wpedantic)
endif()

if(VYSHKAT_COVERAGE AND NOT MSVC)
    target_compile_options(vyshkat_options INTERFACE --coverage -O0 -g)
    target_link_options(vyshkat_options INTERFACE --coverage)
endif()

# Вся логика приложения лежит в библиотеке: её используют программа и тесты.
file(GLOB_RECURSE VYSHKAT_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp"
)
list(FILTER VYSHKAT_SOURCES EXCLUDE REGEX ".*/src/main\\.cpp$")

add_library(vyshkat_core STATIC ${VYSHKAT_SOURCES})
target_include_directories(vyshkat_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(vyshkat_core PUBLIC vyshkat_options)

# Консольное приложение.
add_executable(vyshkat src/main.cpp
        src/models/Validation.h)
target_link_libraries(vyshkat PRIVATE vyshkat_core)

# Юнит-тесты.
if(VYSHKAT_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()