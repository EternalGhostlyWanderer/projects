add_library(contrib_catch2_main
  contrib/catch2/catch_amalgamated.cpp
)

target_include_directories(contrib_catch2_main
  PUBLIC contrib
)
