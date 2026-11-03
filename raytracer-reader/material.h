#pragma once
#include "../raytracer-geom/vector.h"
#include <string>
// ambient_color (Ka), diffuse_color (Kd),
// specular_color (Ks), intensity (Ke),
// specular_exponent (Ns),
// refraction_index (Ni / eta)
// albedo: albedo[0] (al0 - доля Фонга), albedo[1] (al1 - отражение), albedo[2] (al2 - преломление)
struct Material {
    std::string name;
    Vector ambient_color = {0, 0, 0};
    Vector diffuse_color = {0, 0, 0};
    Vector specular_color = {0, 0, 0};
    Vector intensity = {0, 0, 0};
    double specular_exponent = 1;
    double refraction_index = 1;
    Vector albedo = {1, 0, 0};
};
