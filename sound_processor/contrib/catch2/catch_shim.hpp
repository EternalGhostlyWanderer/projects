#ifndef XI_CATCH_SHIM_HPP
#define XI_CATCH_SHIM_HPP

// define which Catch2 header to include
#ifdef XI_CATCH2_INCLUDE_WAY_FULL
  #include <catch2/catch_all.hpp>
#else
  #include "catch_amalgamated.hpp"
#endif

#endif
