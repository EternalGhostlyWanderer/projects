#pragma once

#include "options/camera_options.h"
#include "options/render_options.h"
#include "image.h"

#include <filesystem>

Image Render(const std::filesystem::path& path, const CameraOptions& camera_options,
             const RenderOptions& render_options);
