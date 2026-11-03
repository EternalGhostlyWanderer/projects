#pragma once

#include "vector.h"
#include "sphere.h"
#include "intersection.h"
#include "triangle.h"
#include "ray.h"

#include <optional>

std::optional<Intersection> GetIntersection(const Ray& ray, const Sphere& sphere);
std::optional<Intersection> GetIntersection(const Ray& ray, const Triangle& triangle);

Vector Reflect(const Vector& ray, const Vector& normal);
std::optional<Vector> Refract(const Vector& ray, const Vector& normal, double eta);
Vector GetBarycentricCoords(const Triangle& triangle, const Vector& point);
