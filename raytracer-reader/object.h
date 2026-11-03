#pragma once

#include "../raytracer-geom/triangle.h"
#include "material.h"
#include "../raytracer-geom/sphere.h"
#include "../raytracer-geom/vector.h"

struct Object {
    const Material* material = nullptr;
    Triangle polygon;

    std::array<Vector, 3> normals;
    std::array<bool, 3> has_normals = {false, false, false};

    const Vector* GetNormal(size_t index) const {
        if (has_normals[index]) {
            return &normals[index];
        }
        return nullptr;
    }
};

struct SphereObject {
    const Material* material = nullptr;
    Sphere sphere;
};
