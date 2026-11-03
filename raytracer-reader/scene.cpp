#include "scene.h"
#include <iostream>
#include <fstream>
#include <sstream>
const std::vector<Object>& Scene::GetObjects() const {
    return objects_;
}
const std::vector<SphereObject>& Scene::GetSphereObjects() const {
    return spheres_;
}
const std::vector<Light>& Scene::GetLights() const {
    return lights_;
}
const std::unordered_map<std::string, Material>& Scene::GetMaterials() const {
    return materials_;
}

std::unordered_map<std::string, Material> ReadMaterials(const std::filesystem::path& path) {
    std::unordered_map<std::string, Material> materials;
    std::ifstream file(path);

    if (!file.is_open()) {
        return materials;
    }

    std::string line;
    std::string current_name;

    while (std::getline(file, line)) {

        std::istringstream ss(line);
        std::string type;

        if (ss >> type) {
            if (type == "newmtl") {
                std::string name;
                ss >> name;

                Material mat;
                mat.name = name;
                materials[name] = mat;
                current_name = name;

            } else if (!current_name.empty()) {
                Material& cur = materials[current_name];

                if (type == "Ka") {
                    double r, g, b;
                    ss >> r >> g >> b;
                    cur.ambient_color = Vector(r, g, b);
                } else if (type == "Kd") {
                    double r, g, b;
                    ss >> r >> g >> b;
                    cur.diffuse_color = Vector(r, g, b);
                } else if (type == "Ks") {
                    double r, g, b;
                    ss >> r >> g >> b;
                    cur.specular_color = Vector(r, g, b);
                } else if (type == "Ke") {
                    double r, g, b;
                    ss >> r >> g >> b;
                    cur.intensity = Vector(r, g, b);
                } else if (type == "Ns") {
                    ss >> cur.specular_exponent;
                } else if (type == "Ni") {
                    ss >> cur.refraction_index;
                } else if (type == "al") {
                    double a, b, c;
                    ss >> a >> b >> c;
                    cur.albedo = Vector(a, b, c);
                }
            }
        }
    }
    return materials;
}
Scene ReadScene(const std::filesystem::path& path) {
    Scene scene;
    std::ifstream file(path);
    if (!file.is_open()) {
        return scene;
    }

    std::vector<Vector> v;
    std::vector<Vector> vn;
    const Material* cur = nullptr;
    std::string line;
    while (std::getline(file, line)) {
        std::istringstream ss(line);
        std::string type;
        ss >> type;

        if (type == "v") {
            double x, y, z;
            ss >> x >> y >> z;
            v.emplace_back(x, y, z);

        } else if (type == "vn") {
            double x, y, z;
            ss >> x >> y >> z;
            vn.emplace_back(x, y, z);

        } else if (type == "f") {
            std::vector<std::array<int, 2>> v_and_vn_ind;
            std::string vert;

            while (ss >> vert) {
                int num_v = 0;
                int num_vn = 0;

                size_t first_slash = vert.find('/');
                if (first_slash == std::string::npos) {
                    num_v = std::stoi(vert);
                } else {
                    num_v = std::stoi(vert.substr(0, first_slash));
                    size_t second_slash = vert.find('/', first_slash + 1);
                    if (second_slash != std::string::npos) {
                        // v//vn или v/vt/vn
                        std::string vn_str = vert.substr(second_slash + 1);
                        if (!vn_str.empty()) {
                            num_vn = std::stoi(vn_str);
                        }
                    }
                    // else v/vt
                }

                if (num_v > 0) {
                    num_v = num_v - 1;
                } else {
                    num_v = v.size() + num_v;
                }

                if (num_vn != 0) {
                    if (num_vn > 0) {
                        num_vn = num_vn - 1;
                    } else {
                        num_vn = vn.size() + num_vn;
                    }
                } else {
                    num_vn = -1;
                }

                v_and_vn_ind.push_back({num_v, num_vn});
            }

            for (size_t i = 1; i + 1 < v_and_vn_ind.size(); i++) {
                Object obj{.material = cur,
                           .polygon = Triangle(v[v_and_vn_ind[0][0]], v[v_and_vn_ind[i][0]],
                                               v[v_and_vn_ind[i + 1][0]]),
                           .normals = {},
                           .has_normals = {false, false, false}};

                if (v_and_vn_ind[0][1] != -1) {
                    obj.normals[0] = vn[v_and_vn_ind[0][1]];
                    obj.has_normals[0] = true;
                }
                if (v_and_vn_ind[i][1] != -1) {
                    obj.normals[1] = vn[v_and_vn_ind[i][1]];
                    obj.has_normals[1] = true;
                }
                if (v_and_vn_ind[i + 1][1] != -1) {
                    obj.normals[2] = vn[v_and_vn_ind[i + 1][1]];
                    obj.has_normals[2] = true;
                }

                scene.objects_.push_back(obj);
            }

        } else if (type == "mtllib") {
            std::string mtl_filename;
            ss >> mtl_filename;
            auto mtl_path = path.parent_path() / mtl_filename;
            auto new_mats = ReadMaterials(mtl_path);
            for (const auto& [name, mat] : new_mats) {
                scene.materials_[name] = mat;
            }

        } else if (type == "usemtl") {
            std::string mat_name;
            ss >> mat_name;
            cur = &scene.materials_[mat_name];

        } else if (type == "S") {
            double x, y, z, r;
            ss >> x >> y >> z >> r;
            SphereObject obj{.material = cur, .sphere = Sphere(Vector(x, y, z), r)};
            scene.spheres_.push_back(obj);

        } else if (type == "P") {
            double x, y, z, r, g, b;
            ss >> x >> y >> z >> r >> g >> b;
            Light light;
            light.position = Vector(x, y, z);
            light.intensity = Vector(r, g, b);
            scene.lights_.push_back(light);
        }
    }

    return scene;
}
