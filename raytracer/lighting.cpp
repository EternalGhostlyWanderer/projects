#include "lighting.h"
// Напоминалка по формулам
// ambient_color (Ka), diffuse_color (Kd),
// specular_color (Ks), intensity (Ke),
// specular_exponent (Ns),
// refraction_index (Ni / eta)
// albedo: albedo[0] (al0 - доля Фонга), albedo[1] (al1 - отражение), albedo[2] (al2 - преломление)
// Di = i * max(0, dot(v_l, n))
Vector Diffuse(const Vector& v, const Vector& n, const Vector& i) {
    double temp_dot = DotProduct(v, n);
    return i * std::max(0.0, temp_dot);
}

// Si = i * max(0, dot(v_r, v_lr))^Ns
Vector Specular(const Vector& v, const Vector& lr, const Vector& i, double ns) {
    double temp_dot = DotProduct(v, lr);
    double temp = std::pow(std::max(0.0, temp_dot), ns);
    return i * temp;
}

// Итоговая формула: al0 * (Kd \sum D_i + Ks \sum S_i) + Ka + Ke
Vector ObjectIllum(const Material& mat, const Vector& sum_diff, const Vector& sum_spec) {
    return (mat.diffuse_color * sum_diff + mat.specular_color * sum_spec) * mat.albedo[0] +
           mat.ambient_color + mat.intensity;
}

// al0 * (Kd * sum_D + Ks * sum_S) + Ka + Ke + al1 * i_reflect + al2 * i_refract
// al2 = 1 внутри объекта
Vector FinalIllum(const Material& mat, const Vector& obj_illum, const Vector& i_reflect,
                  const Vector& i_refract, bool is_inside) {

    double al2;
    if (is_inside) {
        al2 = 1;
    } else {
        al2 = mat.albedo[2];
    }
    return obj_illum + i_reflect * mat.albedo[1] + i_refract * al2;
}
