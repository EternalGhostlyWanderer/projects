#pragma once

#include "options/camera_options.h"
#include "../raytracer-geom/ray.h"
#include "../raytracer-geom/vector.h"

struct Matrix4x4 {
    double m[4][4] = {{0}};

    Vector MultiplyPoint(const Vector& p) const {
        double x = m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3];
        double y = m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3];
        double z = m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3];
        return Vector(x, y, z);
    }
};
class Camera {
public:
    Camera(const CameraOptions& options);

    Ray GenerateRay(int x, int y) const;

private:
    Vector look_from_;
    Matrix4x4 camera_to_;
    double scale_;
    double aspect_ratio_;
    int width_;
    int height_;
};
