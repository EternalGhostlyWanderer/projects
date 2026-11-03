#pragma once

#include "vector.h"

class Sphere {
public:
    Sphere(const Vector& center, double radius) : center_(center), rad_(radius) {
    }

    const Vector& GetCenter() const {
        return center_;
    }
    double GetRadius() const {
        return rad_;
    }

private:
    Vector center_;
    double rad_;
};
