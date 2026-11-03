add_library(geom_local STATIC ../raytracer-geom/vector.cpp ../raytracer-geom/geometry.cpp)
target_include_directories(geom_local PUBLIC ../raytracer-geom)

add_library(reader_local STATIC ../raytracer-reader/scene.cpp)
target_include_directories(reader_local PUBLIC ../raytracer-reader)
target_link_libraries(reader_local PUBLIC geom_local)

function(add_target NAME FILE)
    add_catch(${NAME} ${FILE} raytracer.cpp lighting.cpp camera.cpp postprocess.cpp)
    target_include_directories(${NAME} PRIVATE .)
    target_link_libraries(${NAME} PRIVATE reader_local geom_local ${PNG_LIBRARY})
    target_include_directories(${NAME} PRIVATE ${PNG_INCLUDE_DIRS})
endfunction()

add_target(test_raytracer_asan test_asan.cpp)
add_target(test_raytracer_release test_release.cpp)