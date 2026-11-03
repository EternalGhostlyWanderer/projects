#include "camera.h"
#include <cmath>
#include <algorithm>
#include <lighting.h>

Camera::Camera(const CameraOptions& options)
    : look_from_(options.look_from), width_(options.screen_width), height_(options.screen_height) {
    scale_ = std::tan(options.fov * 0.5);
    aspect_ratio_ = static_cast<double>(options.screen_width) / options.screen_height;

    Vector z = look_from_ - options.look_to;
    z.Normalize();
    Vector global_y(0, 1, 0);
    if (std::abs(z[0]) < kEpsilon && std::abs(z[2]) < kEpsilon) {
        if (z[1] > 0) {
            global_y = Vector(0, 0, -1);
        } else {
            global_y = Vector(0, 0, 1);
        }
    }
    Vector x = CrossProduct(global_y, z);
    x.Normalize();

    Vector y = CrossProduct(z, x);
    y.Normalize();

    camera_to_.m[0][0] = x[0];
    camera_to_.m[1][0] = x[1];
    camera_to_.m[2][0] = x[2];
    camera_to_.m[3][0] = 0;

    camera_to_.m[0][1] = y[0];
    camera_to_.m[1][1] = y[1];
    camera_to_.m[2][1] = y[2];
    camera_to_.m[3][1] = 0;

    camera_to_.m[0][2] = z[0];
    camera_to_.m[1][2] = z[1];
    camera_to_.m[2][2] = z[2];
    camera_to_.m[3][2] = 0;

    camera_to_.m[0][3] = look_from_[0];
    camera_to_.m[1][3] = look_from_[1];
    camera_to_.m[2][3] = look_from_[2];
    camera_to_.m[3][3] = 1;
}
Ray Camera::GenerateRay(int x, int y) const {
    double px = (2 * (x + 0.5) / width_ - 1) * aspect_ratio_ * scale_;
    double py = (1 - 2 * (y + 0.5) / height_) * scale_;

    Vector p_cam(px, py, -1);
    Vector p_world = camera_to_.MultiplyPoint(p_cam);

    Vector ray_dir = p_world - look_from_;
    ray_dir.Normalize();

    return Ray(look_from_, ray_dir);
}
