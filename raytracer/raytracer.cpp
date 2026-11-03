#include "raytracer.h"
#include "camera.h"
#include "lighting.h"
#include "postprocess.h"
#include "../raytracer-geom/ray.h"
#include "../raytracer-reader/scene.h"
#include "../raytracer-geom/geometry.h"

Vector Trace(const Ray& ray, const Scene& scene, int depth, RenderMode mode) {
    if (depth == 0) {
        return Vector(0, 0, 0);
    }

    double min_dist = -1;
    const Object* hit_obj = nullptr;
    const SphereObject* hit_sphere = nullptr;
    Intersection best_intersect(Vector(0, 0, 0), Vector(0, 0, 0), -1);

    for (size_t i = 0; i < scene.GetObjects().size(); i++) {
        auto hit = GetIntersection(ray, scene.GetObjects()[i].polygon);
        if (hit && hit->GetDistance() > kEpsilon) {
            if (min_dist < 0 || hit->GetDistance() < min_dist) {
                min_dist = hit->GetDistance();
                hit_obj = &scene.GetObjects()[i];
                hit_sphere = nullptr;
                best_intersect = *hit;
            }
        }
    }

    for (size_t i = 0; i < scene.GetSphereObjects().size(); i++) {
        auto hit = GetIntersection(ray, scene.GetSphereObjects()[i].sphere);
        if (hit && hit->GetDistance() > kEpsilon) {
            if (min_dist < 0 || hit->GetDistance() < min_dist) {
                min_dist = hit->GetDistance();
                hit_obj = nullptr;
                hit_sphere = &scene.GetSphereObjects()[i];
                best_intersect = *hit;
            }
        }
    }

    if (min_dist < 0) {
        return Vector(0, 0, 0);
    }

    if (mode == RenderMode::kDepth) {
        return Vector(min_dist, min_dist, min_dist);
    }

    const Material* mat_ptr = nullptr;
    Vector normal(0, 0, 0);
    bool is_inside = false;

    if (hit_obj != nullptr) {
    mat_ptr = hit_obj->material;

    normal = best_intersect.GetNormal();
    Vector geom_normal = normal;



    if (DotProduct(ray.GetDirection(), geom_normal) > 0.0) {
        is_inside = true;
    }
} else if (hit_sphere != nullptr) {
        mat_ptr = hit_sphere->material;
        Vector geom_normal = best_intersect.GetPosition() - hit_sphere->sphere.GetCenter();
        geom_normal.Normalize();

        if (DotProduct(ray.GetDirection(), geom_normal) > 0.0) {
            normal *= -1.0;
            is_inside = true;
        }
        normal = geom_normal;
    }

    Vector shading_normal = normal;
    if (is_inside) {
        shading_normal = normal * -1.0;
    }

    if (mode == RenderMode::kNormal) {
        return (shading_normal + Vector(1, 1, 1)) * 0.5;
    }

    Vector pos = best_intersect.GetPosition();
    Vector sum_diffuse(0, 0, 0);
    Vector sum_specular(0, 0, 0);

    for (size_t i = 0; i < scene.GetLights().size(); i++) {
        const Light& light = scene.GetLights()[i];
        Vector vl = light.position - pos;
        double dist_to_light = Length(vl);
        vl.Normalize();

        double n_dot_l = DotProduct(vl, shading_normal);
        if (n_dot_l > 0.0) {
            // Проверка тени
            Vector shadow_origin = pos + shading_normal * kEpsilon;
            Ray shadow_ray(shadow_origin, vl);
            bool in_shadow = false;

            for (size_t j = 0; j < scene.GetObjects().size(); ++j) {
                auto hit = GetIntersection(shadow_ray, scene.GetObjects()[j].polygon);
                if (hit && hit->GetDistance() > kEpsilon && hit->GetDistance() < dist_to_light) {
                    in_shadow = true;
                    break;
                }
            }
            if (!in_shadow) {
                for (size_t j = 0; j < scene.GetSphereObjects().size(); ++j) {
                    auto hit = GetIntersection(shadow_ray, scene.GetSphereObjects()[j].sphere);
                    if (hit && hit->GetDistance() > kEpsilon &&
                        hit->GetDistance() < dist_to_light) {
                        in_shadow = true;
                        break;
                    }
                }
            }

            if (!in_shadow) {
                sum_diffuse += Diffuse(vl, shading_normal, light.intensity);
                Vector reflect_dir = Reflect(vl * -1.0, shading_normal);
                reflect_dir.Normalize();
                Vector v_e = ray.GetDirection() * -1.0;
                v_e.Normalize();
                sum_specular +=
                    Specular(v_e, reflect_dir, light.intensity, mat_ptr->specular_exponent);
            }
        }
    }

    // Отражение
    Vector i_reflect(0, 0, 0);
    if (mat_ptr->albedo[1] > kEpsilon && !is_inside) {
        Vector ref_dir = Reflect(ray.GetDirection(), shading_normal);
        ref_dir.Normalize();
        Ray ref_ray(pos + shading_normal * kEpsilon, ref_dir);
        i_reflect = Trace(ref_ray, scene, depth - 1, mode);
    }

    // Преломление
    Vector i_refract(0, 0, 0);
    if (mat_ptr->albedo[2] > kEpsilon) {
        double eta = is_inside ? mat_ptr->refraction_index : (1.0 / mat_ptr->refraction_index);
        auto refract_dir = Refract(ray.GetDirection(), shading_normal, eta);
        if (refract_dir) {
            Vector refr_dir = *refract_dir;
            refr_dir.Normalize();
            Ray refr_ray(pos - shading_normal * kEpsilon, refr_dir);
            i_refract = Trace(refr_ray, scene, depth - 1, mode);
        }
    }

    Vector direct_light = ObjectIllum(*mat_ptr, sum_diffuse, sum_specular);
    return FinalIllum(*mat_ptr, direct_light, i_reflect, i_refract, is_inside);
}

Image Render(const std::filesystem::path& path, const CameraOptions& camera_options,
             const RenderOptions& render_options) {
    Scene scene = ReadScene(path);
    Camera camera(camera_options);

    int width = camera_options.screen_width;
    int height = camera_options.screen_height;
    std::vector<Vector> data(width * height);

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            Ray ray = camera.GenerateRay(x, y);
            Vector color = Trace(ray, scene, render_options.depth, render_options.mode);
            data[y * width + x] = color;
        }
    }

    Image result_image(width, height);
    Postprocessing(data, result_image, width, height);

    return result_image;
}
