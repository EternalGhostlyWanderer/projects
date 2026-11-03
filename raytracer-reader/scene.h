#pragma once

#include "material.h"
#include "object.h"
#include "light.h"

#include <vector>
#include <unordered_map>
#include <string>
#include <filesystem>

class Scene {
public:
    const std::vector<Object>& GetObjects() const;
    const std::vector<SphereObject>& GetSphereObjects() const;
    const std::vector<Light>& GetLights() const;
    const std::unordered_map<std::string, Material>& GetMaterials() const;

private:
    friend Scene ReadScene(const std::filesystem::path& path);
    std::vector<Object> objects_;
    std::vector<SphereObject> spheres_;
    std::vector<Light> lights_;
    std::unordered_map<std::string, Material> materials_;
};

std::unordered_map<std::string, Material> ReadMaterials(const std::filesystem::path& path);
Scene ReadScene(const std::filesystem::path& path);
