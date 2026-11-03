#pragma once

#include "vector.h"

class Intersection {
public:
    Intersection(const Vector& position, const Vector& normal, double distance)
        : pos_(position), normal_(normal), dist_(distance) {
    }

    const Vector& GetPosition() const {
        return pos_;
    }
    const Vector& GetNormal() const {
        return normal_;
    }
    double GetDistance() const {
        return dist_;
    }

private:
    Vector pos_;
    Vector normal_;
    double dist_;
};
