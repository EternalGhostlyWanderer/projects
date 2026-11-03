#pragma once

#include "vector.h"

#include <cstddef>

class Triangle {
public:
    Triangle(const Vector& a, const Vector& b, const Vector& c) : vert_{a, b, c} {
    }

    const Vector& operator[](size_t ind) const {
        return vert_[ind];
    }
    double Area() const {
        Vector edge1 = vert_[1] - vert_[0];
        Vector edge2 = vert_[2] - vert_[0];
        return 0.5 * Length(CrossProduct(edge1, edge2));
    }

private:
    std::array<Vector, 3> vert_;
};
