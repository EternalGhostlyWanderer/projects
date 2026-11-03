#include "geometry.h"
std::optional<Intersection> GetIntersection(const Ray& ray, const Sphere& sphere) {
    /* уравнений луча P = O + tD и сферы (P - C)^2 = R^2
     * Подстановка дает уравнение at^2 + bt + c = 0, где:
     * a = D \cdot D
     * b = 2 * (D \cdot OC) (где OC = Origin - Center)
     * c = OC \cdot OC - R^2
     *ищем t*/
    Vector oc = ray.GetOrigin() - sphere.GetCenter();

    double a = DotProduct(ray.GetDirection(), ray.GetDirection());
    double b = 2 * DotProduct(oc, ray.GetDirection());
    double c = DotProduct(oc, oc) - sphere.GetRadius() * sphere.GetRadius();

    double discriminant = b * b - 4 * a * c;

    if (discriminant < 0) {
        return std::nullopt;
    }

    double sqrt_disc = std::sqrt(discriminant);
    double t1 = (-b - sqrt_disc) / (2 * a);
    double t2 = (-b + sqrt_disc) / (2 * a);
    double t = t1;
    if (t < 0) {
        t = t2;
        if (t < 0) {
            return std::nullopt;
        }
    }

    Vector point = ray.GetOrigin() + ray.GetDirection() * t;

    Vector normal = point - sphere.GetCenter();
    normal.Normalize();
    if (DotProduct(ray.GetDirection(), normal) > 0.0) {
        normal *= -1.0;
    }

    return Intersection(point, normal, t);
}
std::optional<Intersection> GetIntersection(const Ray& ray, const Triangle& triangle) {
    constexpr double kEpsilon = std::numeric_limits<double>::epsilon();

    Vector edge1 = triangle[1] - triangle[0];
    Vector edge2 = triangle[2] - triangle[0];

    Vector ray_cross_e2 = CrossProduct(ray.GetDirection(), edge2);
    double det = DotProduct(edge1, ray_cross_e2);

    if (std::fabs(det) < kEpsilon) {
        return std::nullopt;
    }

    double inv_det = 1 / det;
    Vector s = ray.GetOrigin() - triangle[0];
    double u = inv_det * DotProduct(s, ray_cross_e2);

    if (u < -kEpsilon || u - 1 > kEpsilon) {
        return std::nullopt;
    }
    Vector s_cross_e1 = CrossProduct(s, edge1);
    double v = inv_det * DotProduct(ray.GetDirection(), s_cross_e1);

    if (v < -kEpsilon || u + v - 1 > kEpsilon) {
        return std::nullopt;
    }
    double t = inv_det * DotProduct(edge2, s_cross_e1);

    if (t > kEpsilon) {
        Vector hit_position = ray.GetOrigin() + ray.GetDirection() * t;

        Vector normal = CrossProduct(edge1, edge2);
        normal.Normalize();

        if (DotProduct(ray.GetDirection(), normal) > 0) {
            normal *= -1.0;
        }

        return Intersection(hit_position, normal, t);
    }

    return std::nullopt;
}

Vector Reflect(const Vector& ray, const Vector& normal) {
    return (ray - normal * (2 * DotProduct(ray, normal)));
}

std::optional<Vector> Refract(const Vector& ray, const Vector& normal, double eta) {
    // R = eta * I - (eta * dot(N, I) + sqrt(k)) * N;
    double dot = DotProduct(normal, ray);
    double k = 1 - eta * eta * (1 - dot * dot);

    if (k < 0) {
        return std::nullopt;
    }

    return eta * ray - (eta * dot + std::sqrt(k)) * normal;
}

Vector GetBarycentricCoords(const Triangle& triangle, const Vector& point) {
    Vector v0 = triangle[1] - triangle[0];
    Vector v1 = triangle[2] - triangle[0];
    Vector v2 = point - triangle[0];

    double d00 = DotProduct(v0, v0);
    double d01 = DotProduct(v0, v1);
    double d11 = DotProduct(v1, v1);
    double d20 = DotProduct(v2, v0);
    double d21 = DotProduct(v2, v1);

    double denom = d00 * d11 - d01 * d01;

    double b1 = (d11 * d20 - d01 * d21) / denom;
    double b2 = (d00 * d21 - d01 * d20) / denom;
    double b0 = 1 - b1 - b2;

    return Vector(b0, b1, b2);
}
