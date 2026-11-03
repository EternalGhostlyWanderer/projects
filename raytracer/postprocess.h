#pragma once

#include "../raytracer-geom/vector.h"
#include "image.h"
#include <vector>
double ToneMapping(double v_in, double c_sq);
double GammaCorrection(double v_out);
void Postprocessing(const std::vector<Vector>& hdr_buffer, Image& out_image, int width, int height);
