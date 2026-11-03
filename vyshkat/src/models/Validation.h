#pragma once

#include <cmath>
#include <stdexcept>

// Расход энергии должен быть конечным неотрицательным числом.
// Значения nan и inf, которые принимает разбор ввода, отклоняются здесь.
inline void requireValidEnergy(double dailyEnergyKwh) {
    if (!std::isfinite(dailyEnergyKwh) || dailyEnergyKwh < 0) {
        throw std::invalid_argument(
            "Расход энергии должен быть неотрицательным числом"
        );
    }
}