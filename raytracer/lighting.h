#pragma once

#include "../raytracer-geom/ray.h"
#include "../raytracer-geom/vector.h"
#include "../raytracer-reader/scene.h"
#include "../raytracer-reader/material.h"
#include "../raytracer-geom/intersection.h"
// ambient_color (Ka), diffuse_color (Kd),
// specular_color (Ks), intensity (Ke),
// specular_exponent (Ns),
// refraction_index (Ni / eta)
// albedo: albedo[0] (al0 - доля Фонга), albedo[1] (al1 - отражение), albedo[2] (al2 - преломление)

constexpr double kEpsilon = 1e-5;

Vector Diffuse(const Vector& v, const Vector& n, const Vector& I);

Vector Specular(const Vector& r, const Vector& lr, const Vector& I, double ns);

// al0 * (Kd * sum_D + Ks * sum_S) + Ka + Ke
Vector ObjectIllum(const Material& mat, const Vector& sum_diffuse, const Vector& sum_specular);
// al0 * (Kd * sum_D + Ks * sum_S) + Ka + Ke + al1 * I_reflect + al2 *
// al2 = 1 внутри объекта
Vector FinalIllum(const Material& mat, const Vector& direct_light, const Vector& reflect_light,
                  const Vector& refract_light, bool is_inside);
