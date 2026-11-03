include(FetchContent)

# Берём GoogleTest, установленный в системе. Если его нет, скачиваем
# (при первой настройке проекта нужен интернет).
find_package(GTest QUIET)

if(NOT GTest_FOUND)
    FetchContent_Declare(
        googletest
        URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
    )

    # Для MSVC: единая библиотека времени выполнения с нашим проектом.
    set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
    set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)

    FetchContent_MakeAvailable(googletest)
endif()

if(TARGET GTest::gtest_main)
    set(VYSHKAT_GTEST_MAIN GTest::gtest_main)
else()
    set(VYSHKAT_GTEST_MAIN gtest_main)
endif()

include(GoogleTest)

file(GLOB_RECURSE VYSHKAT_TEST_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
)

add_executable(vyshkat_tests ${VYSHKAT_TEST_SOURCES})

# Позволяет писать #include "fakes/FakeInspectionService.h".
target_include_directories(vyshkat_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(vyshkat_tests PRIVATE vyshkat_core ${VYSHKAT_GTEST_MAIN})

gtest_discover_tests(vyshkat_tests)