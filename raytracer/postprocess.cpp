#include "postprocess.h"

#include <iostream>
#include <lighting.h>
double ToneMapping(double v_in, double c) {
    double num = v_in * (1.0 + v_in / c);
    double den = 1.0 + v_in;
    return num / den;
}

double GammaCorrection(double v_out) {
    return std::pow(v_out, 1 / 2.2);
}

void Postprocessing(const std::vector<Vector>& data, Image& image, int width, int height) {
    double c_temp = 0;
    for (const Vector& pixel : data) {
        c_temp = std::max(c_temp, std::max(pixel[0], std::max(pixel[1], pixel[2])));
    }

    if (c_temp < kEpsilon) {
        c_temp = 1;
    }
    double c = c_temp * c_temp;

    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            const Vector& old_color = data[y * width + x];
            Vector new_color;

            for (int i = 0; i < 3; i++) {
                new_color[i] = GammaCorrection(ToneMapping(old_color[i], c));
                new_color[i] = std::clamp(new_color[i], 0.0, 1.0);
            }

            RGB rgb_pixel;
            int r = static_cast<int>(std::round(new_color[0] * 255.0));
            rgb_pixel.r = std::clamp(r, 0, 255);

            int g = static_cast<int>(std::round(new_color[1] * 255.0));
            rgb_pixel.g = std::clamp(g, 0, 255);

            int b = static_cast<int>(std::round(new_color[2] * 255.0));
            rgb_pixel.b = std::clamp(b, 0, 255);

            image.SetPixel(rgb_pixel, y, x);
        }
    }
}
