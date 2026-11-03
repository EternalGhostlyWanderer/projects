# This modules serves like a shim allowing to choose between a fullfledged Catch2 CMake-project
# or its simplified amalgamized version


# select only one option

#----<Option 1: full-fledged CMake-project >----

# # include Catch2 library in the project
# add_subdirectory(lib/Catch2)
# add_library(XiCatch2WithMain ALIAS Catch2WithMain)
# target_include_directories(Catch2WithMain PUBLIC contrib)
# add_compile_definitions(XI_CATCH2_INCLUDE_WAY_FULL)


#----<Option 2: amalgamized catch2 simplified approach >----
find_package(Catch2 REQUIRED)
add_library(XiCatch2WithMain ALIAS contrib_catch2_main)
