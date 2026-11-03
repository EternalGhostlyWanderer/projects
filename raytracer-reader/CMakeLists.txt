add_catch(test_raytracer_reader test.cpp scene.cpp vector.cpp)

target_include_directories(test_raytracer_reader PRIVATE ../raytracer-geom)